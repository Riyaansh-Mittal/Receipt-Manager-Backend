import base64
import json
import logging
import time
from typing import Dict, Any, List
from django.conf import settings
import google.generativeai as genai
import re

from ..utils.exceptions import (
    GeminiServiceException,
    DataExtractionException,
    ModelLoadingException,
)

logger = logging.getLogger(__name__)

class GeminiExtractionService:
    """
    Use Gemini AI to extract structured data AND categorize in ONE call.
    Supports text input or image input modes.
    """
    GEMINI_MAX_RETRIES = 2  # Total 3 attempts
    GEMINI_RETRY_BACKOFF = [2, 4]  # 2s, 4s exponential
    MIN_IMAGE_SIZE = 50 * 1024  # 50KB minimum
    
    def __init__(self):
        self.model_name = 'gemini-2.0-flash-exp'
        self.timeout = 30
        self._gemini_client = None
        self._initialization_error = None
        
        # Debug mode - prints to console if enabled
        self.debug_mode = getattr(settings, 'GEMINI_DEBUG_MODE', False)
        
        self._initialize_client()
    
    def _debug_print(self, message: str, level: str = "INFO", truncate: int = None):
        if self.debug_mode:
            print(f"\n{'='*80}")
            print(f"[GEMINI {level}] ", end="")
            if truncate is not None and len(message) > truncate:
                print(f"{message[:truncate]}... [truncated, total length: {len(message)} chars]")
            else:
                print(message)
            print(f"{'='*80}\n")
    
    def _debug_section(self, title: str, content: str, truncate: int = None):
        if self.debug_mode:
            print(f"\n{'='*80}")
            print(f"[GEMINI DEBUG] {title}")
            print(f"{'-'*80}")
            if truncate and len(content) > truncate:
                print(f"{content[:truncate]}")
                print(f"... [truncated, total length: {len(content)} chars]")
            else:
                print(content)
            print(f"{'='*80}\n")

    def _initialize_client(self) -> None:
        try:
            api_key = getattr(settings, 'GOOGLE_GEMINI_API_KEY', None)
            if not api_key:
                self._initialization_error = "GOOGLE_GEMINI_API_KEY not configured"
                logger.error(self._initialization_error)
                return
            
            genai.configure(api_key=api_key)
            
            generation_config = {
                "temperature": 0.1,
                "top_p": 0.8,
                "top_k": 20,
                "max_output_tokens": 1500,
                "response_mime_type": "application/json",
            }
            
            safety_settings = [
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_ONLY_HIGH"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_ONLY_HIGH"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_ONLY_HIGH"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_ONLY_HIGH"},
            ]
            
            self._gemini_client = genai.GenerativeModel(
                model_name=self.model_name,
                generation_config=generation_config,
                safety_settings=safety_settings
            )
            logger.info(f"Gemini extraction service initialized: {self.model_name}")
            self._debug_print(f"Initialized with model: {self.model_name}")
            
        except Exception as e:
            self._initialization_error = str(e)
            logger.error(f"Failed to initialize Gemini: {str(e)}", exc_info=True)
            self._gemini_client = None

    def get_engine_info(self) -> Dict[str, Any]:
        return {
            'engine': self.model_name,
            'available': self._gemini_client is not None,
            'error': self._initialization_error,
        }

    def extract_and_categorize(
        self,
        ocr_text: str,
        receipt_id: str,
        user_id: str,
        categories: List[Dict[str, str]],
    ) -> Dict[str, Any]:
        """
        Extract structured data AND categorize in ONE Gemini API call from OCR text.
        """
        # ✅ FIX: Enhanced input validation
        if not ocr_text or not isinstance(ocr_text, str):
            logger.warning(f"Invalid OCR text for receipt {receipt_id}")
            return self._get_fallback_extraction_result('Invalid or missing OCR text')
        
        if len(ocr_text.strip()) < 50:  # Increased from 25
            logger.warning(f"OCR text too short for receipt {receipt_id}: {len(ocr_text)} chars")
            return self._get_fallback_extraction_result('Insufficient OCR text extracted')
        
        if not categories or not isinstance(categories, list):
            logger.warning(f"Invalid categories for receipt {receipt_id}")
            categories = []
        
        prompt = self._build_extraction_prompt(ocr_text, categories)
        return self._call_gemini_api(prompt, receipt_id)
    
    def extract_from_image(
        self,
        preprocessed_image: bytes,
        receipt_id: str,
        user_id: str,
        categories: List[Dict[str, str]],
    ) -> Dict[str, Any]:
        """
        Extract structured data and categorize from a preprocessed image directly.

        Uses Gemini's multimodal API: send image bytes as a separate part,
        not as base64 embedded in text. This matches official examples. [web:38][web:42][web:43]
        """
        # ✅ Fast-fail for invalid input
        if not preprocessed_image or len(preprocessed_image) < self.MIN_IMAGE_SIZE:
            logger.warning(f"Image too small for receipt {receipt_id}: {len(preprocessed_image)} bytes")
            return self._get_fallback_extraction_result('Image quality too low')
        
        if not categories or not isinstance(categories, list):
            categories = []
        
        # Max 20MB image size
        if len(preprocessed_image) > 20 * 1024 * 1024:
            logger.warning(f"Image too large for receipt {receipt_id}: {len(preprocessed_image)} bytes")
            return self._get_fallback_extraction_result('Image exceeds 20MB limit')
        
        # Build text instructions prompt
        intro_text = (
            "You are an expert at analyzing receipt images and extracting structured data.\n"
            "Use the provided image to infer vendor, date, amounts, line items, and best category.\n"
        )
        
        prompt = self._build_extraction_prompt_with_intro(intro_text, categories)
        
        # Build image part
        image_part = {
            "mime_type": "image/jpeg",  # Adjust if preprocessing produces PNG
            "data": preprocessed_image,
        }
        
        contents = [prompt, image_part]
        from google.api_core.exceptions import ResourceExhausted, DeadlineExceeded
        # ✅ Production retry logic
        for attempt in range(self.GEMINI_MAX_RETRIES + 1):
            try:
                if attempt > 0:
                    sleep_time = self.GEMINI_RETRY_BACKOFF[attempt - 1]
                    logger.warning(f"Gemini retry {attempt}/{self.GEMINI_MAX_RETRIES} in {sleep_time}s")
                    time.sleep(sleep_time)
                
                response = self._call_gemini_api(contents, receipt_id)
                
                # ✅ Quality gate - immediate fallback on low confidence
                if response['extraction_confidence']['overall'] < 0.3:
                    logger.warning(f"Low confidence for receipt {receipt_id}, using fallback")
                    return self._get_fallback_extraction_result('Low confidence extraction')
                
                return response
                
            except DeadlineExceeded as timeout_error:
                logger.warning(f"Gemini timeout (attempt {attempt + 1})")
                if attempt == self.GEMINI_MAX_RETRIES:
                    return self._get_fallback_extraction_result('AI service timeout')
                continue
                
            except ResourceExhausted as quota_error:
                retry_seconds = getattr(quota_error, 'retry_delay', type('obj', (object,), {'seconds': 5}))().seconds
                logger.warning(f"Quota exhausted, retry in {retry_seconds}s")
                if attempt == self.GEMINI_MAX_RETRIES:
                    return self._get_fallback_extraction_result('API quota exhausted')
                time.sleep(retry_seconds)
                continue
                
            except (GeminiServiceException, ModelLoadingException) as hard_error:
                # ✅ Hard failure - don't retry, let pipeline mark as 'failed'
                logger.error(f"Hard Gemini error: {str(hard_error)}")
                raise
                
            except Exception as unexpected_error:
                logger.error(f"Unexpected Gemini error: {str(unexpected_error)}")
                if attempt == self.GEMINI_MAX_RETRIES:
                    return self._get_fallback_extraction_result('Unexpected AI error')
                continue

    # ---------------- CORE CALL ---------------- #

    def _call_gemini_api(
        self,
        contents: List[Any],  # can be [text] or [text, image_part]
        receipt_id: str,
    ) -> Dict[str, Any]:
        """
        Call Gemini with either:
        - text only: contents=['prompt text']
        - image + text: contents=['prompt text', {'mime_type': 'image/jpeg', 'data': image_bytes}]
        This follows official multimodal usage for google-generativeai. [web:42]
        """
        if not self._gemini_client:
            error_msg = f"Client not initialized: {self._initialization_error}"
            logger.error(error_msg)
            self._debug_print(f"{error_msg}", "ERROR")
            raise ModelLoadingException(
                detail="Gemini client not initialized",
                context={'error': self._initialization_error},
            )

        start_time = time.time()
        # NOTE: google-generativeai GenerativeModel expects contents=[...]
        response = self._gemini_client.generate_content(
            contents,
            request_options={"timeout": self.timeout},
        )
        elapsed = time.time() - start_time

        if self.debug_mode:
            self._debug_print(f"[GEMINI RESPONSE] Received in {elapsed:.2f}s", "INFO")
            self._debug_print(f"Raw response text:\n{response.text}", truncate=3000)

        if not response or not getattr(response, "text", None):
            logger.error("Empty response from Gemini")
            self._debug_print("Empty response!", "ERROR")
            return self._get_fallback_extraction_result('Empty response from AI')

        response_text = self._strip_markdown(response.text)
        response_text = self._fix_json_formatting(response_text)

        try:
            result = json.loads(response_text)
            if self.debug_mode:
                self._debug_print(
                    "[GEMINI RESULT] Successfully parsed JSON",
                    "SUCCESS",
                )
                self._debug_print(json.dumps(result, indent=2), "SUCCESS", truncate=3000)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Gemini JSON: {str(e)}")
            self._debug_print(f"JSON parse error: {str(e)}", "ERROR")
            if self.debug_mode:
                self._debug_print(f"Response text:\n{response_text[:500]}")
            return self._get_fallback_extraction_result('Invalid AI response format')

        try:
            self._validate_result(result, receipt_id)
        except Exception as ve:
            logger.error(f"Gemini result validation failed: {ve}")
            self._debug_print(f"Validation error: {ve}", "ERROR")
            return self._get_fallback_extraction_result('Invalid extraction result structure')

        return result

    def _build_extraction_prompt(self, ocr_text: str, categories: List[Dict[str, str]]) -> str:
        """Build prompt for OCR text input mode"""
        category_list = self._format_categories(categories)
        max_ocr_length = 3000
        truncated_ocr = ocr_text[:max_ocr_length]
        if len(ocr_text) > max_ocr_length:
            truncated_ocr += "\n... [truncated]"

        prompt = f"""You are an expert at analyzing receipt text and extracting structured information with high accuracy.

**Receipt OCR Text:**
{truncated_ocr}

**Available Categories:**
{category_list}

**Instructions:**
1. Extract ALL relevant information from the receipt text
2. Parse dates in various formats and convert to YYYY-MM-DD
3. Identify the final total amount (after tax)
4. Detect currency from symbols ($, €, £, ₹, etc) or text
5. Choose the most appropriate category based on vendor name and context
6. If information is unclear or missing, use null (not empty strings)
7. Be careful with OCR errors: O vs 0, I/l vs 1, S vs 5, etc
8. Provide confidence scores (0.0 to 1.0) for each extracted field

**Response Format (JSON only, no additional text):**
{{
  "extracted_data": {{
    "vendor_name": "string or null",
    "receipt_date": "YYYY-MM-DD or null",
    "total_amount": number or null,
    "currency": "USD" or detected code,
    "tax_amount": number or null,
    "subtotal": number or null,
    "line_items": [
      {{"description": "string", "price": number, "quantity": number}}
    ],
  }},
  "category_prediction": {{
    "category_id": "ID from categories list or null",
    "category_name": "name from list or null",
    "confidence": 0.85,
    "reasoning": "brief explanation"
  }},
  "extraction_confidence": {{
    "vendor_name": 0.9,
    "date": 0.8,
    "amount": 0.95,
    "overall": 0.88
  }}
}}

**Important:**
- Return ONLY valid JSON
- Use null for missing data, not empty strings
- Total amount should be the final amount paid
- Category must be from the provided list or null if unsure
- Confidence scores must be between 0.0 and 1.0
- Be accurate with numbers - don't confuse 0/O or 1/I

Respond ONLY with valid JSON, no additional text."""
        return prompt

    def _build_extraction_prompt_with_intro(self, intro_text: str, categories: List[Dict[str, str]]) -> str:
        """Build prompt for image input mode, reusing main prompt structure"""
        category_list = self._format_categories(categories)

        prompt = f"""{intro_text}

**Available Categories:**
{category_list}

**Instructions:**
1. Extract ALL relevant information from the receipt image
2. Parse dates in various formats and convert to YYYY-MM-DD
3. Identify the final total amount (after tax)
4. Detect currency from symbols ($, €, £, ₹, etc) or text
5. Choose the most appropriate category based on vendor name and context
6. If information is unclear or missing, use null (not empty strings)
7. Be careful with image artifacts and distortions
8. Provide confidence scores (0.0 to 1.0) for each extracted field

**Response Format (JSON only, no additional text):**
{{
  "extracted_data": {{
    "vendor_name": "string or null",
    "receipt_date": "YYYY-MM-DD or null",
    "total_amount": number or null,
    "currency": "USD" or detected code,
    "tax_amount": number or null,
    "subtotal": number or null,
    "line_items": [
      {{"description": "string", "price": number, "quantity": number}}
    ],
  }},
  "category_prediction": {{
    "category_id": "ID from categories list or null",
    "category_name": "name from list or null",
    "confidence": 0.85,
    "reasoning": "brief explanation"
  }},
  "extraction_confidence": {{
    "vendor_name": 0.9,
    "date": 0.8,
    "amount": 0.95,
    "overall": 0.88
  }}
}}

**Important:**
- Return ONLY valid JSON
- Use null for missing data, not empty strings
- Total amount should be the final amount paid
- Category must be from the provided list or null if unsure
- Confidence scores must be between 0.0 and 1.0
- Be accurate with numbers

Respond ONLY with valid JSON, no additional text."""
        return prompt

    def _format_categories(self, categories: List[Dict[str, str]]) -> str:
        if not categories:
            return "- No categories available"
        return "\n".join([f"- {cat['name']} (ID: {cat['id']})" for cat in categories])

    def _get_fallback_extraction_result(self, reason: str) -> Dict[str, Any]:
        logger.warning(f"Using fallback extraction result due to: {reason}")
        return {
            'extracted_data': {
                'vendor_name': None,
                'receipt_date': None,
                'total_amount': None,
                'currency': None,
                'tax_amount': None,
                'subtotal': None,
                'line_items': [],
            },
            'category_prediction': {
                'category_id': None,
                'category_name': None,
                'confidence': 0.0,
                'reasoning': reason,
            },
            'extraction_confidence': {
                'vendor_name': 0.0,
                'date': 0.0,
                'amount': 0.0,
                'overall': 0.0,
            }
        }

    def _strip_markdown(self, text: str) -> str:
        text = text.strip()
        if text.startswith('```'):
            text = text[7:]
        elif text.startswith('```'):
            text = text[3:]
        if text.endswith('```'):
            text = text[:-3]
        return text.strip()

    def _fix_json_formatting(self, text: str) -> str:
        """Fix common JSON formatting issues from LLMs"""
        # Remove trailing commas before closing brackets/braces
        text = re.sub(r',\s*}', '}', text)
        text = re.sub(r',\s*]', ']', text)
        return text

    def _validate_result(self, result: Dict[str, Any], receipt_id: str) -> None:
        required_keys = ['extracted_data', 'category_prediction', 'extraction_confidence']
        for key in required_keys:
            if key not in result:
                raise DataExtractionException(detail=f"Missing required key in response: {key}",
                                              context={'receipt_id': receipt_id, 'missing_key': key})
        extracted = result['extracted_data']
        if not isinstance(extracted, dict):
            raise DataExtractionException(detail="extracted_data must be a dictionary",
                                          context={'receipt_id': receipt_id})
        category = result['category_prediction']
        if not isinstance(category, dict):
            raise DataExtractionException(detail="category_prediction must be a dictionary",
                                          context={'receipt_id': receipt_id})
        if 'confidence' in category:
            try:
                confidence = float(category['confidence'])
                if not 0.0 <= confidence <= 1.0:
                    logger.warning(f"Confidence out of range: {confidence}")
            except (ValueError, TypeError):
                raise DataExtractionException(detail="Invalid confidence score",
                                              context={'receipt_id': receipt_id})

# Global instance
gemini_extractor = GeminiExtractionService()
