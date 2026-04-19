from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routes.articles import router as articles_router
from .routes.search import router as search_router

app = FastAPI(title="Wiki Search API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(search_router, prefix="/api", tags=["search"])
app.include_router(articles_router, prefix="/api", tags=["articles"])


@app.get("/")
async def root():
    return {"message": "Wiki Search API is running"}


@app.get("/health")
async def health():
    return {"status": "ok"}