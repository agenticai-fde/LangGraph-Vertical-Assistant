"""Shared settings: Supabase client and Ollama chat model.

Reads the .env file at the repository root (found by walking up from this folder).
"""
import os
from functools import lru_cache

from dotenv import find_dotenv, load_dotenv
from langchain_ollama import ChatOllama
from supabase import Client, create_client

load_dotenv(find_dotenv())


@lru_cache(maxsize=1)
def get_db() -> Client:
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("Set SUPABASE_URL and SUPABASE_KEY in the .env file at the repo root.")
    return create_client(url, key)


@lru_cache(maxsize=1)
def get_llm() -> ChatOllama:
    return ChatOllama(
        model=os.getenv("OLLAMA_MODEL", "qwen2.5:3b"),
        base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        temperature=0,
    )
