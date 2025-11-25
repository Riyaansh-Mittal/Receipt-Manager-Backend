# ai_service/management/commands/test_gemini.py

from django.core.management.base import BaseCommand
from django.conf import settings
import google.generativeai as genai


class Command(BaseCommand):
    help = 'Test Gemini API connection and categorization'

    def add_arguments(self, parser):
        parser.add_argument(
            '--model',
            type=str,
            default='gemini-2.5-flash',
            help='Model name to test'
        )

    def handle(self, *args, **options):
        model_name = options['model']
        
        try:
            # Configure Gemini
            api_key = settings.GOOGLE_GEMINI_API_KEY
            if not api_key:
                self.stdout.write(self.style.ERROR(' GEMINI_API_KEY not configured'))
                return
            
            self.stdout.write(f"Testing Gemini API with model: {model_name}")
            self.stdout.write(f"API Key: {api_key[:10]}...{api_key[-4:]}")
            
            genai.configure(api_key=api_key)
            
            # Test 1: Simple hello
            self.stdout.write("\n1. Testing simple generation...")
            model = genai.GenerativeModel(model_name)
            response = model.generate_content("Say 'Hello'")
            self.stdout.write(self.style.SUCCESS(f" Response: {response.text}"))
            
            # Test 2: Category prediction
            self.stdout.write("\n2. Testing category prediction...")
            prompt = """
            Analyze this receipt and suggest a category:
            
            Receipt Text: Walmart Supercenter - Groceries $45.99
            
            Categories: Groceries, Dining, Transportation, Shopping, Other
            
            Respond with just the category name.
            """
            
            response = model.generate_content(prompt)
            self.stdout.write(self.style.SUCCESS(f" Category: {response.text}"))
            
            # Test 3: Check quota
            self.stdout.write("\n3. Checking API status...")
            models = list(genai.list_models())
            self.stdout.write(self.style.SUCCESS(f" Found {len(models)} available models"))
            
            self.stdout.write(self.style.SUCCESS('\n✅ All tests passed!'))
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'\n Test failed: {str(e)}'))
            
            # Check common issues
            if 'API key' in str(e):
                self.stdout.write(self.style.WARNING('\nPossible issue: Invalid API key'))
            elif 'quota' in str(e).lower():
                self.stdout.write(self.style.WARNING('\nPossible issue: API quota exceeded'))
            elif 'not found' in str(e).lower():
                self.stdout.write(self.style.WARNING(f'\nPossible issue: Model {model_name} not available'))
