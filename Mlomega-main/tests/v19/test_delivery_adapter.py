import pytest
pytestmark = pytest.mark.transport

import importlib.util, sys
import json
from pathlib import Path


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, Path(path)); mod = importlib.util.module_from_spec(spec); sys.modules[name]=mod; spec.loader.exec_module(mod); return mod

delivery_adapter = load('delivery_adapter', 'services/live-pc/delivery_adapter.py')


def test_delivery_row_maps_to_brainlive_context_card_ui_intent():
    intent = delivery_adapter.delivery_row_to_ui_intent({'delivery_id':'d1','message':'hello','action_type':'notify','priority':0.7,'evidence_json':'{"evidence_refs":["x"]}'})
    assert intent.producer == 'brainlive'
    assert intent.component == 'context_card'
    assert intent.delivery_id == 'd1'
    assert intent.evidence_refs == ['x']

def test_h1_task_panel_keeps_component_content_stable_id_and_ttl():
    candidate = {
        'kind': 'task_panel', 'ui_intent_id': 'help-panel:task-1', 'ttl_ms': 123456,
        'evidence_refs': ['frame:1'],
    }
    intent = delivery_adapter.delivery_row_to_ui_intent({
        'delivery_id': 'd-help', 'message': json.dumps({
            'title': 'Réparer',
            'steps': [{'index': 0, 'text': 'Visse', 'status': 'current'}],
            'ghost_next': False,
        }), 'action_type': 'context_card', 'priority': 0.55,
        'evidence_json': json.dumps({'candidate': candidate}),
    })
    assert intent.producer == 'ultralive'
    assert intent.component == 'task_panel'
    assert intent.ui_intent_id == 'help-panel:task-1'
    assert intent.ttl_ms == 123456
    assert intent.content['steps'][0]['status'] == 'current'
    assert intent.evidence_refs == ['frame:1']

def test_websocket_renderer_hub_broadcasts_uiintent_json():
    import asyncio

    async def run_case():
        class FakeWebSocket:
            def __init__(self):
                self.accepted = False
                self.messages = []
            async def accept(self):
                self.accepted = True
            async def send_text(self, payload):
                self.messages.append(payload)

        hub = delivery_adapter.WebSocketRendererHub()
        ws = FakeWebSocket()
        await hub.connect(ws)
        intent = delivery_adapter.delivery_row_to_ui_intent({'delivery_id':'d-ws','message':'hello ws','action_type':'notify','priority':1,'evidence_json':'{}'})
        await hub.push(intent)

        assert ws.accepted is True
        assert ws.messages
        assert 'hello ws' in ws.messages[0]
        assert intent in hub.sent

    asyncio.run(run_case())
