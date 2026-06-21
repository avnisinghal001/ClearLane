import pandas as pd
import numpy as np

def calculate_eis_and_resources(event_type: str, event_cause: str, priority: str, requires_road_closure: int):
    """
    SDLC Rule-Based Expert Engine to calculate Event Impact Score (EIS) 
    and dynamically allocate resources for Khushboo's frontend dashboard.
    """
    # 1. Base weights definition
    type_weights = {"unplanned": 40, "planned": 20, "disaster": 50}
    
    # Priority mapping according to dataset values (handling common variations)
    priority_weights = {"high": 30, "medium": 15, "low": 5, "p1": 30, "p2": 20, "p3": 10}
    
    # Normalize inputs to lowercase string to avoid matching bugs
    e_type = str(event_type).lower().strip()
    e_cause = str(event_cause).lower().strip()
    prio = str(priority).lower().strip()
    
    # Calculate base component scores
    score = type_weights.get(e_type, 15) # Default fallback if type mismatch
    score += priority_weights.get(prio, 10)
    
    # Factor in critical closures
    if requires_road_closure == 1 or str(requires_road_closure).lower() in ['true', 'yes']:
        score += 20
        
    # High impact triggers (e.g., waterlogging, protests, accidents spike the score)
    high_impact_causes = ["waterlogging", "accident", "protest", "rally", "vip_movement"]
    if any(cause in e_cause for cause in high_impact_causes):
        score += 10

    # Clip the final score tightly between 0 and 100
    eis_score = int(np.clip(score, 0, 100))
    
    # 2. Risk Level Tagging
    if eis_score >= 75:
        risk_level = "High"
    elif eis_score >= 45:
        risk_level = "Medium"
    else:
        risk_level = "Low"
        
    # 3. Resource Allocation Rules (Dynamic numbers based on EIS severity)
    if risk_level == "High":
        manpower = int(eis_score * 0.15)
        barricades = int(eis_score * 0.3)
    elif risk_level == "Medium":
        manpower = int(eis_score * 0.1)
        barricades = int(eis_score * 0.2)
    else:
        manpower = int(max(2, eis_score * 0.05))
        barricades = int(max(0, eis_score * 0.1))
        
    return {
        "eis_score": eis_score,
        "risk_level": risk_level,
        "recommendations": {
            "manpower_required": manpower,
            "barricades_needed": barricades
        }
    }

def get_historical_clusters():
    """
    Extracts high density sample clusters from the CSV to build Khushboo's map heatmap markers.
    """
    try:
        df = pd.read_csv("Astram event data.csv", low_memory=False)
        # Drop rows with invalid coordinates
        df = df.dropna(subset=['latitude', 'longitude'])
        # Sample 50 active points to avoid freezing the Leaflet UI map
        sample_df = df.sample(n=min(50, len(df)), random_state=42)
        
        clusters = []
        for _, row in sample_df.iterrows():
            clusters.append({
                "id": str(row['id']),
                "event_type": str(row['event_type']),
                "cause": str(row.get('event_cause', 'General Congestion')),
                "lat": float(row['latitude']),
                "lng": float(row['longitude']),
                "priority": str(row.get('priority', 'Medium'))
            })
        return clusters
    except Exception as e:
        print(f"Error fetching clusters: {e}")
        return []

# Test run to verify calculations
if __name__ == "__main__":
    test_run = calculate_eis_and_resources("unplanned", "waterlogging_near_junction", "high", 1)
    print("\n🔬 Engine Test Run Output:")
    print(test_run)