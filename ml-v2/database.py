import os
import pandas as pd
from sqlalchemy import create_engine, text

# Your Live Neon Connection String
DATABASE_URL = "postgresql://neondb_owner:npg_3ApiysGo8vKr@ep-spring-star-aop3hmjp.c-2.ap-southeast-1.aws.neon.tech/neondb?sslmode=require"

# Initialize SQLAlchemy Engine
engine = create_engine(DATABASE_URL)

def test_db_connection():
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT NOW();"))
            print(f"✅ Cloud DB Connected Successfully! Server Time: {result.fetchone()[0]}")
            return True
    except Exception as e:
        print(f"❌ DB Connection Failed: {e}")
        return False

def seed_database_sample():
    """Reads ASTraM CSV and uploads a sample to the cloud PostgreSQL database"""
    try:
        csv_filename = "Astram event data.csv"
        if not os.path.exists(csv_filename):
            print(f"❌ Error: {csv_filename} nahi mili! Pehle check karo.")
            return
        
        print("⏳ Data process ho raha hai cloud upload ke liye...")
        df = pd.read_csv(csv_filename, low_memory=False)
        
        # Selecting crucial columns to keep it lightweight
        columns_to_keep = ['id', 'event_type', 'latitude', 'longitude', 'event_cause', 'priority', 'requires_road_closure']
        df_sample = df[columns_to_keep].dropna(subset=['latitude', 'longitude']).head(100)
        
        # Upload to Neon Database as a table named 'incidents'
        print("🚀 Syncing with Neon Cloud... Database table populate ho rahi hai...")
        df_sample.to_sql('incidents', con=engine, if_exists='replace', index=False)
        print("🔥 BOOM! Top 100 historical incidents uploaded to Neon Cloud Database successfully!")
        
    except Exception as e:
        print(f"❌ Upload Failed: {e}")

if __name__ == "__main__":
    if test_db_connection():
        seed_database_sample()