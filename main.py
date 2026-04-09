from fastapi import FastAPI, Header, HTTPException, status, Depends
from supabase import create_client, Client
from pydantic import BaseModel
from supabase_auth.errors import AuthApiError
from fastapi.middleware.cors import CORSMiddleware
import requests
import os
import sys
from dotenv import load_dotenv
import traceback
from urllib.parse import urlparse

# Fix encoding for Windows console to support Arabic characters
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

load_dotenv()

app = FastAPI()

def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


AIRTABLE_TOKEN = require_env("AIRTABLE_TOKEN")
base_id = require_env("BASE_ID")
table_name = "Clients response"
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Login(BaseModel):
    email: str
    password: str


class Register(BaseModel):
    user_name: str
    email: str
    password: str


class Data(BaseModel):
    name: str
    number: str


def normalize_number(number: str) -> str:
    """Normalize phone number for comparison (remove +, spaces, dashes, etc.)"""
    # Remove common phone number formatting
    normalized = number.replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "").strip()
    return normalized

def airtable_record_exists(table: str, number: str) -> bool:
    """Return True if a record with the given Number exists in the Airtable table."""
    url = f"https://api.airtable.com/v0/{base_id}/{table}"
    headers = {"Authorization": f"Bearer {AIRTABLE_TOKEN}"}
    
    # Normalize the input number for comparison
    normalized_input = normalize_number(number)
    
    print(f"\n{'='*60}")
    print(f"Checking number '{number}' (normalized: '{normalized_input}') in table '{table}'")
    print(f"{'='*60}")

    try:
        all_records = []
        offset = None
        
        # Fetch all records with pagination
        while True:
            params = {
                "maxRecords": 100,
                "fields[]": ["Number"],  # Only fetch Number field for efficiency
            }
            
            if offset:
                params["offset"] = offset

            response = requests.get(url, headers=headers, params=params)
            
            print(f"  Request Status: {response.status_code}")
            
            if response.status_code != 200:
                error_data = response.json() if response.content else {}
                error_msg = error_data.get("error", {}).get("message", "Unknown error")
                print(f"  ❌ Error: {error_msg}")
                print(f"  Full response: {response.text}")
                return False

            data = response.json()
            records = data.get("records", [])
            all_records.extend(records)
            
            print(f"  Fetched {len(records)} records (total so far: {len(all_records)})")
            
            # Check for pagination
            offset = data.get("offset")
            if not offset:
                break
        
        print(f"\n  📊 Total records in '{table}': {len(all_records)}")
        
        if len(all_records) == 0:
            print(f"  ✓ Table is empty - number does not exist")
            return False
        
        # Check each record's number (normalized) against the input
        print(f"\n  🔍 Comparing against {len(all_records)} records:")
        match_found = False
        for idx, record in enumerate(all_records, 1):
            record_number = record.get("fields", {}).get("Number", "")
            if record_number:
                normalized_record = normalize_number(str(record_number))
                match = normalized_record == normalized_input
                status = "✓ MATCH" if match else "✗"
                print(f"    [{idx}] {status} | Original: '{record_number}' | Normalized: '{normalized_record}' | ID: {record.get('id')}")
                if match:
                    match_found = True
                    print(f"\n  ⚠️  MATCH FOUND! Record ID: {record.get('id')}")
            else:
                print(f"    [{idx}] ⚠️  Record has no Number field | ID: {record.get('id')}")
        
        if not match_found:
            print(f"\n  ✓ No matching number found in '{table}'")
        
        return match_found
        
    except Exception as e:
        print(f"  ❌ Exception checking number: {str(e)}")
        import traceback
        traceback.print_exc()
        # If there's an exception, don't block the save
        return False


def verify_token(auth: str = Header(None)):
    if not auth:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
        )

    try:
        token = auth.split(" ")[1]
    except IndexError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format",
        )

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token not found"
        )

    try:
        user = supabase.auth.get_user(token)
        if not user or not user.user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
            )
        print("user_id:", user.user.id)
        return user.user

    except AuthApiError as e:
        # Handle expired or invalid tokens
        if "expired" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired"
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )
supabase_url = require_env("SUPABASE_URL")
supabase_service_role_key = require_env("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(supabase_url, supabase_service_role_key)


def _debug_supabase_dns() -> None:
    try:
        host = urlparse(supabase_url).hostname
        print(f"Supabase host: {host!r}")
        if host:
            import socket
            print("Supabase getaddrinfo (sample):", socket.getaddrinfo(host, 443)[:1])
    except Exception:
        traceback.print_exc()


@app.post("/login")
def login(user: Login):
    try:
        response = supabase.auth.sign_in_with_password(
            {"email": user.email, "password": user.password}
        )

        # Check for error using the attribute
        if response.user is None:
            # Usually response.message has the error info
            return {"error": response.message or "Invalid login"}

        # Access user and session as attributes
        return {"user": response.user, "session": response.session}

    except Exception as e:
        return {"error": str(e)}


# التسجيل
@app.post("/register")
def register(user: Register):
    try:
        response = supabase.auth.sign_up(
            {
                "email": user.email,
                "password": user.password,
                "options": {"data": {"DisplayName": user.user_name}},
            }
        )

        # Check for error using the attribute
        if response.user is None:
            # Usually response.message has the error info
            error_msg = response.message or "Registration failed"
            print("Register error:", error_msg)
            raise HTTPException(status_code=400, detail=error_msg)

        # Access user and session as attributes
        print("Register success:", response)
        return {"user": response.user, "session": response.session}

    except HTTPException:
        raise
    except AuthApiError as e:
        # Forward Supabase Auth errors with a more accurate HTTP status.
        msg = str(e)
        status_code = status.HTTP_400_BAD_REQUEST
        if "rate limit" in msg.lower() or "too many" in msg.lower():
            status_code = status.HTTP_429_TOO_MANY_REQUESTS
        elif "expired" in msg.lower():
            status_code = status.HTTP_401_UNAUTHORIZED
        print("Register AuthApiError:", msg)
        _debug_supabase_dns()
        raise HTTPException(status_code=status_code, detail=msg)
    except Exception as e:
        print("Register exception:", str(e))
        _debug_supabase_dns()
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))


class AirtableQuery(BaseModel):
    pageSize: int | None = None
    maxRecords: int | None = None
    offset: str | None = None
    view: str | None = None
    filterByFormula: str | None = None
    cellFormat: str | None = None
    fields: list[str] | None = None
    returnFieldsByFieldId: bool | None = None


@app.post("/airtable")
def list_records(user=Depends(verify_token)):
    url = f"https://api.airtable.com/v0/{base_id}/{table_name}"
    headers = {"Authorization": f"Bearer {AIRTABLE_TOKEN}"}

    params = {
        k: v
        for k, v in {
            "pageSize": 10,
            "view": "Grid view",
            "cellFormat": "string",
            "fields": ["Name", "Number", "Intent", "Date"],
        }.items()
        if v is not None
    }

    if params.get("cellFormat") == "string":
        params.setdefault("timeZone", "UTC")
        params.setdefault("userLocale", "en")

    response = requests.get(url, headers=headers, params=params)
    data = response.json()

    # فلتر الـ records - بس اللي فيها Name
    if "records" in data:
        data["records"] = [
            r for r in data["records"] if r.get("fields", {}).get("Name")
        ]

    print(data)
    return data


@app.post("/airtable/save_clients")
def save_clients(client: Data, user=Depends(verify_token)):
    table_name = "Clients"
    url = f"https://api.airtable.com/v0/{base_id}/{table_name}"

    headers = {
        "Authorization": f"Bearer {AIRTABLE_TOKEN}",
        "Content-Type": "application/json",
    }

    print(f"\n=== Attempting to save client ===")
    print(f"Name: {client.name}")
    print(f"Number: {client.number}")

    # Prevent duplicate numbers in Clients table only
    exists_in_clients = airtable_record_exists("Clients", client.number)
    
    print(f"Exists in Clients: {exists_in_clients}")
    
    if exists_in_clients:
        print(f"ERROR: Number {client.number} already exists in Clients table!")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Number already exists",
        )

    # Create a new record in Airtable
    body = {
        "fields": {
            "Name": client.name,
            "Number": client.number,
        }
    }

    response = requests.post(url, json=body, headers=headers)
    
    print(f"Airtable POST Status: {response.status_code}")
    
    if response.status_code >= 400:
        error_data = response.json() if response.content else {}
        error_msg = error_data.get("error", {}).get("message", "Failed to save record")
        print(f"Airtable Error: {error_msg}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to save: {error_msg}",
        )
    
    data = response.json()
    print(f"Airtable Insert Success: {data}")
    print(f"=== Save completed ===\n")

    return data


@app.post("/airtable/getclients")
def list_clients_records(query: AirtableQuery, user=Depends(verify_token)):
    table_name = "Clients"

    url = f"https://api.airtable.com/v0/{base_id}/{table_name}"
    headers = {"Authorization": f"Bearer {AIRTABLE_TOKEN}"}

    # Force returning only Name and Number from Airtable API
    params = {
        "pageSize": 10,
        "view": "Grid view",
        "cellFormat": "string",
        "fields[]": ["Name", "Number"],  # <--- ALWAYS request these 2 fields
        "timeZone": "UTC",
        "userLocale": "en",
    }

    response = requests.get(url, headers=headers, params=params)
    data = response.json()
    print(data)

    # Make sure that only Name + Number are returned in every record
    if "records" in data:
        for record in data["records"]:
            fields = record.get("fields", {})
            record["fields"] = {
                "Name": fields.get("Name"),
                "Number": fields.get("Number"),
            }

    return data
@app.delete("/airtable/delete_client/{record_id}")
def delete_client(record_id: str):
    table_name = "Clients"
    url = f"https://api.airtable.com/v0/{base_id}/{table_name}/{record_id}"

    headers = {
        "Authorization": f"Bearer {AIRTABLE_TOKEN}",
    }

    response = requests.delete(url, headers=headers)
    data = response.json()

    print("Airtable Delete Response:", data)

    return data

 