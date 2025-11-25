# auth_service/management/commands/reset_database.py

from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.conf import settings
from django.db import connections
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
import os


class Command(BaseCommand):
    help = 'Drop and recreate PostgreSQL database, then run migrations'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Skip confirmation',
        )
        parser.add_argument(
            '--no-migrate',
            action='store_true',
            help='Skip migrations after dropping database',
        )
    
    def handle(self, *args, **options):
        """Drop and recreate PostgreSQL database using Python"""

        # Safety check: prevent running in production
        environment = os.getenv('DJANGO_ENVIRONMENT', 'development').lower()
        if environment == 'production':
            self.stdout.write(self.style.ERROR(
                "\n❌ Aborted: This command is disabled in production environment.\n"
            ))
            return
        
        # Get database settings
        db_settings = settings.DATABASES['default']
        db_name = db_settings['NAME']
        db_user = db_settings['USER']
        db_password = db_settings.get('PASSWORD', '')
        db_host = db_settings.get('HOST', 'localhost')
        db_port = db_settings.get('PORT', '5432')
        
        # Confirmation
        if not options['force']:
            self.stdout.write(
                self.style.WARNING(
                    f'\n⚠️  This will:'
                    f'\n  - DROP database: {db_name}'
                    f'\n  - CREATE new database: {db_name}'
                    f'\n  - RUN all migrations'
                    f'\n\n⚠️  ALL DATA WILL BE LOST!'
                )
            )
            
            confirm = input(f'\nType "{db_name}" to confirm: ')
            
            if confirm != db_name:
                self.stdout.write(self.style.ERROR('\n❌ Aborted.\n'))
                return
        
        self.stdout.write('\n🗑️  Resetting database...\n')
        
        try:
            # Step 1: Close Django connections
            self.stdout.write('  Closing Django connections...')
            connections.close_all()
            self.stdout.write(self.style.SUCCESS('✓ Closed Django connections'))
            
            # Step 2: Connect to 'postgres' database to drop/create
            self.stdout.write(f'\n  Connecting to PostgreSQL...')
            
            conn = psycopg2.connect(
                dbname='postgres',  # Connect to default postgres database
                user=db_user,
                password=db_password,
                host=db_host,
                port=db_port
            )
            
            # Set autocommit (required for CREATE/DROP DATABASE)
            conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            cursor = conn.cursor()
            
            self.stdout.write(self.style.SUCCESS('✓ Connected to PostgreSQL'))
            
            # Step 3: Terminate existing connections to target database
            self.stdout.write(f'\n  Terminating connections to {db_name}...')
            
            terminate_query = f"""
                SELECT pg_terminate_backend(pg_stat_activity.pid)
                FROM pg_stat_activity
                WHERE pg_stat_activity.datname = '{db_name}'
                AND pid <> pg_backend_pid();
            """
            
            try:
                cursor.execute(terminate_query)
                self.stdout.write(self.style.SUCCESS('✓ Terminated existing connections'))
            except Exception as e:
                self.stdout.write(
                    self.style.NOTICE(f'  No active connections to terminate')
                )
            
            # Step 4: Drop database
            self.stdout.write(f'\n  Dropping database {db_name}...')
            
            drop_query = f'DROP DATABASE IF EXISTS "{db_name}";'
            cursor.execute(drop_query)
            
            self.stdout.write(self.style.SUCCESS(f'✓ Dropped database {db_name}'))
            
            # Step 5: Create database
            self.stdout.write(f'\n  Creating database {db_name}...')
            
            create_query = f"CREATE DATABASE \"{db_name}\" WITH ENCODING 'UTF8';"
            cursor.execute(create_query)
            
            self.stdout.write(self.style.SUCCESS(f'✓ Created database {db_name}'))
            
            # Close connection
            cursor.close()
            conn.close()
            
            # Step 6: Run migrations
            if not options['no_migrate']:
                self.stdout.write('\n📦 Running migrations...\n')
                call_command('migrate', verbosity=1)
                
                self.stdout.write(
                    self.style.SUCCESS('\n✓ Migrations completed')
                )
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'\n✅ Database {db_name} reset successfully!\n'
                )
            )
            
            # Show next steps
            self.stdout.write(
                self.style.NOTICE(
                    '\n📋 Next steps:'
                    '\n  1. python manage.py createsuperuser'
                    '\n  2. python manage.py loaddata initial_categories'
                    '\n'
                )
            )
            
        except psycopg2.OperationalError as e:
            self.stdout.write(
                self.style.ERROR(
                    f'\n❌ Database connection error:'
                    f'\n   {str(e)}'
                    f'\n\n💡 Make sure PostgreSQL is running and credentials are correct.'
                )
            )
        
        except psycopg2.Error as e:
            self.stdout.write(
                self.style.ERROR(
                    f'\n❌ PostgreSQL error:'
                    f'\n   {str(e)}'
                )
            )
        
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'\n❌ Unexpected error: {str(e)}\n')
            )
            import traceback
            traceback.print_exc()
