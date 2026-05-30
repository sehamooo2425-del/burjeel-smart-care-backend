"""
supabase.py — Creates and exports the shared Supabase database client.

Supabase is a cloud-hosted Postgres database with a Python SDK. This module
reads the connection credentials from environment variables and constructs a
single client object that every other module can import and reuse, avoiding
the overhead of creating a new connection on every request.
"""

import os
from supabase import create_client, Client
from dotenv import load_dotenv

# Load variables from the .env file into os.environ so they are accessible below.
load_dotenv()

# Read the two required secrets from the environment.
url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_SERVICE_KEY")  # Service key grants full DB access.

# Fail loudly at startup rather than mysteriously at query time if the credentials
# are missing — this makes configuration mistakes much easier to diagnose.
if not url or not key:
    raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")

# The Client type annotation is just documentation — it tells your editor what
# methods are available on 'supabase' without changing how Python runs the code.
supabase: Client = create_client(url, key)
