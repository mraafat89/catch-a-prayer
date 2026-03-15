from fastapi import APIRouter

router = APIRouter(tags=["settings"])


@router.get("/settings")
async def get_settings():
    return {
        "default_radius_km": 10,
        "congregation_window_minutes": 15,
        "travel_buffer_minutes": 5,
        "show_adhan_times": True,
        "show_iqama_times": True,
        "show_data_source": True,
        "calculation_method": "ISNA",
    }
