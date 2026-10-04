from fastapi import FastAPI

app = FastAPI(title="PGS Search Engine API")


@app.get("/")
def hello_world():
    return {"message": "Hello, World!"}



