from fastapi import FastAPI

app=FastAPI(title="Order Service", version="0.1.0")

@app.get("/health")
def health_check():
    return {"status": "ok"}
