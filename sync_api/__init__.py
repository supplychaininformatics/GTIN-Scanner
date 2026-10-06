"""sync_api — REST service that handheld clients sync through.

Run separately from the Streamlit app:

    uvicorn sync_api.app:create_app --factory --host 0.0.0.0 --port 8080

See SYNC-API.md for the client contract.
"""
