import os
from supabase import create_client, Client


def get_supabase_client(service_role: bool = False) -> Client:
    url = os.environ["SUPABASE_URL"]
    key = (
        os.environ["SUPABASE_SERVICE_ROLE_KEY"]
        if service_role
        else os.environ.get("SUPABASE_ANON_KEY", "")
    )
    return create_client(url, key)
