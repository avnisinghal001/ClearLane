import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text
import pandas as pd

# Import the trained ML & Routing core
from ml_routing_engine import brain

app = FastAPI(title="Astram Traffic Intelligence API - AI Powered", version="3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATABASE_URL = "postgresql://neondb_owner:npg_3ApiysGo8vKr@ep-spring-star-aop3hmjp.c-2.ap-southeast-1.aws.neon.tech/neondb?sslmode=require"

# 🚀 DB CRASH FIX: pool_pre_ping aur pool_recycle Neon DB ke connection ko sone (sleep) nahi denge
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=300)

@app.get("/")
def home():
    return {"status": "Online", "mode": "CatBoost ML & NetworkX Engine Active On Cloud"}

@app.get("/api/v1/forecast")
def get_live_forecast(
    event_type: str = "unplanned",
    event_cause: str = "vehicle_breakdown",
    priority: str = "medium",
    requires_road_closure: str = "0" # 🚀 DATA FIX: Isko string rakha taaki crash na ho
):
    # 🚀 AI 50 BUG FIX: Yahan string ko properly integer me badal rahe hain model ke liye
    closure_int = 1 if str(requires_road_closure).lower() in ["1", "true", "yes"] else 0
    
    # ML Prediction Call
    ai_score = brain.predict_impact(priority, closure_int)
    
    risk_level = "High" if ai_score >= 70 else ("Medium" if ai_score >= 40 else "Low")
    manpower = int(ai_score * 0.15) if risk_level == "High" else int(ai_score * 0.08)
    barricades = int(ai_score * 0.25) if risk_level == "High" else int(ai_score * 0.12)

    coord_mapping = {
        "vehicle_breakdown": {"lat": 12.9720, "lng": 77.6194},
        "waterlogging": {"lat": 12.9556, "lng": 77.6200},
        "accident": {"lat": 12.9716, "lng": 77.5946},
        "protest": {"lat": 12.9218, "lng": 77.5750}
    }
    location = coord_mapping.get(event_cause.lower(), {"lat": 12.9716, "lng": 77.5946})

    return {
        "event_id": "ASTRAM-AI-PRED",
        "location": location,
        "event_type": event_type,
        "cause": event_cause,
        "eis_score": ai_score,
        "risk_level": risk_level,
        "recommendations": {
            "manpower_required": max(2, manpower),
            "barricades_needed": max(0, barricades)
        }
    }

@app.get("/api/v1/routes")
def get_routes(priority: str = "medium"):
    is_high_risk = str(priority).lower() in ["high", "p1", "3"]
    return brain.calculate_dynamic_diversion(is_high_risk=is_high_risk)

@app.get("/api/v1/historical-clusters")
def get_db_clusters():
    try:
        with engine.connect() as conn:
            query = text("SELECT id, event_type, latitude, longitude, event_cause, priority FROM incidents;")
            df = pd.read_sql(query, conn)
            clusters = []
            for _, row in df.iterrows():
                clusters.append({
                    "id": str(row['id']),
                    "event_type": str(row['event_type']),
                    "cause": str(row['event_cause']),
                    "lat": float(row['latitude']),
                    "lng": float(row['longitude']),
                    "priority": str(row['priority'])
                })
            return {"status": "success", "total_points": len(clusters), "data": clusters}
    except Exception as e:
        return {"status": "error", "message": str(e), "data": []}