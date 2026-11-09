from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
import pymupdf


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setenv('STUDYREAD_DATA_DIR', str(tmp_path / 'data'))
    from studyread import store
    store.initialize()


@pytest.fixture
def textbook(tmp_path):
    from studyread import store
    source = tmp_path / 'Mechanics.pdf'
    with pymupdf.open() as doc:
        for i in range(5):
            page = doc.new_page(width=520, height=720)
            page.insert_text((60, 80), f'Chapter {i + 1}: Newtonian mechanics', fontsize=20)
            page.insert_text((60, 150), f'Page {i + 1} states that force equals mass times acceleration.\nF = m a', fontsize=13)
            page.insert_text((60, 240), 'Consider the motion of a particle under a constant force.', fontsize=12)
        doc.set_metadata({'title': 'Introduction to Mechanics', 'author': 'Example author'})
        doc.set_toc([[1, 'Chapter 1', 1], [2, '1.1 Newton laws', 2], [1, 'Chapter 2', 4]])
        doc.save(source)
    return store.add_book(source)['book']


@pytest.fixture
def model():
    from studyread import config
    config.save_settings({'profiles': [{'id': 'mock', 'name': 'Test model', 'baseUrl': 'http://127.0.0.1:9',
                                        'apiKey': 'test-only-key', 'provider': 'openai', 'model': 'mock-model',
                                        'vision': True}], 'activeProfile': 'mock'})
    return config.profile()
