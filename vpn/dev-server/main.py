from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://10.35.156.201:5173"],  # Add your frontend origin(s) here
    allow_credentials=True,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)
@app.get("/ping")
async def ping(request: Request):
    client_ip = request.client.host
    return {
        "message": f"IP: {client_ip}"
    }