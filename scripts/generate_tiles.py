# generate_tiles.py
import os
import json
import sys
import subprocess
from supabase import create_client, Client
from dotenv import load_dotenv

# Load environment variables from .env file for local development
load_dotenv()

# --- Configuration ---
# Supabase connection details from environment variables
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY")

# Supabase table and storage details
SOURCE_VIEW_NAME = "external_articles_geojson"
STORAGE_BUCKET_NAME = "tiles"
OUTPUT_PMTILES_FILE = "articles.pmtiles"
OUTPUT_GEOJSON_FILE = "articles.geojson"

# Tippecanoe options
# Adjust these as needed for your map visualization.
# -o: output file
# -Z: min zoom
# -z: max zoom
# --force: overwrite existing file
# --no-tile-compression: can be useful for some clients
# --drop-densest-as-needed: helps manage tile size
TIPPECANOE_OPTIONS = [
    "tippecanoe",
    "-o", OUTPUT_PMTILES_FILE,      # output file
    "-l", "articles",             # layer name
    "--minimum-zoom", "0",                    # min zoom
    "--maximum-zoom", "19",                   # max zoom
    "--force",                    # overwrite if exists
    # "--no-feature-limit",         # keep all features
    # "--no-tile-size-limit",       # don’t drop geometry due to size
    "--preserve-input-order",     # preserve order of features
    # "--no-tile-compression",      # optional: keeps tiles uncompressed for debugging
    "--drop-rate=0",
    "--cluster-distance=0",  # cluster points closer than this (in pixels)
    "--drop-densest-as-needed",
    "--gamma=1", # helps with small features
    "--extend-zooms-if-still-dropping",
    OUTPUT_GEOJSON_FILE           # input GeoJSON
]

# --- Initialization ---

if not all([SUPABASE_URL, SUPABASE_SECRET_KEY]):
    print("Error: SUPABASE_URL and SUPABASE_SECRET_KEY environment variables must be set.", file=sys.stderr)
    sys.exit(1)

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)
except Exception as e:
    print(f"Error initializing Supabase client: {e}", file=sys.stderr)
    sys.exit(1)

# --- Core Functions ---

def fetch_data_as_geojson(client: Client) -> dict:
    """Fetches data from Supabase and converts it to a GeoJSON FeatureCollection."""
    print(f"Fetching data from '{SOURCE_VIEW_NAME}' view...")
    resp = client.table(SOURCE_VIEW_NAME).select("url, title, location, marker").execute()
    rows = resp.data
    features = []
    for i, row in enumerate(rows):
        geom = None
        if location_data := row.get("location"):
            try:
                # If location is a string, parse it. Otherwise, assume it's valid GeoJSON.
                geom = json.loads(location_data) if isinstance(location_data, str) else location_data
            except json.JSONDecodeError:
                print(f"Warning: Could not parse location for row {i}. Skipping geometry.", file=sys.stderr)
                geom = None

        feature = {
            "type": "Feature", 
            "id": i,
            "geometry": geom,        
            "properties": {            
                "url": row.get("url"),
                "title": row.get("title"),
                "marker": row.get("marker"),
            },
        }
        features.append(feature)

    print(f"Fetched {len(features)} features.")
    return {"type": "FeatureCollection", "features": features}
   
def save_geojson_to_file(geojson_data: dict, filename: str):
    """Saves GeoJSON data to a local file."""
    print(f"Saving GeoJSON data to '{filename}'...")
    with open(filename, 'w') as f:
        json.dump(geojson_data, f)
    print("GeoJSON file saved.")

def generate_tiles():
    """Generates PMTiles vector tiles using tippecanoe."""
    print("Generating PMTiles with tippecanoe...")
    print(f"Running command: {' '.join(TIPPECANOE_OPTIONS)}")
    subprocess.run(TIPPECANOE_OPTIONS, check=True)
    print("PMTiles generated.")

def upload_to_storage(client: Client):
    """Uploads the generated PMTiles file to Supabase Storage."""
    print(f"Uploading '{OUTPUT_PMTILES_FILE}' to bucket '{STORAGE_BUCKET_NAME}'...")
    # It's crucial to set the content type for PMTiles to enable HTTP Range Requests.
    file_options = {"contentType": "application/octet-stream", "cache-control": "3600", "upsert": "true"}
    try:
        with open(OUTPUT_PMTILES_FILE, 'rb') as f:
            response = client.storage.from_(STORAGE_BUCKET_NAME).upload(
                path=OUTPUT_PMTILES_FILE,
                file=f,
                file_options=file_options,
            )
        print("Upload successful.")
    except Exception as e:
        print(f"Error uploading to storage: {e}")
        raise

def cleanup_files(*filenames):
    """Removes specified files from the local filesystem."""
    print("\nCleaning up generated files...")
    for filename in filenames:
        try:
            os.remove(filename)
            print(f"Removed '{filename}'.")
        except FileNotFoundError:
            print(f"'{filename}' not found, skipping cleanup.")
        except Exception as e:
            print(f"Warning: Could not remove file {filename}. Error: {e}", file=sys.stderr)

def main():
    """Main execution function."""
    try:
        # 1. Fetch data and create GeoJSON
        geojson_data = fetch_data_as_geojson(supabase)
        if not geojson_data or not geojson_data['features']:
            print("No features to process. Exiting.")
            return

        # 2. Save GeoJSON to a file
        save_geojson_to_file(geojson_data, OUTPUT_GEOJSON_FILE)

        # 3. Generate PMTiles via tippecanoe
        generate_tiles()

        # 4. Upload the PMTiles file to Supabase Storage
        upload_to_storage(supabase)

        print("\n✅ PMTiles generation and upload complete!")
    finally:
        # 5. Clean up local files
        cleanup_files(OUTPUT_GEOJSON_FILE, OUTPUT_PMTILES_FILE)

if __name__ == "__main__":
    main()
