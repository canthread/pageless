import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from pageless.app import create_app
from pageless.config import Settings
from pageless.db import Base, make_engine
from pageless.retriever import retrieve
from pageless.seed import seed


@pytest.fixture
def settings():
    return Settings(database_url="sqlite://", composer="fallback", _env_file=None)


@pytest.fixture
def session(settings):
    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    with sessionmaker(engine)() as s:
        seed(s)
        yield s


@pytest.fixture
def ctx_for(session):
    return lambda path: retrieve(session, path)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c
