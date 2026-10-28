import json
from src.browser_agent.agent import ActionPlan

data = json.loads(json.dumps({
    "actions": [
        {"type": "type", "target": "e160", "text": "zhang"},
        {"action": "click", "target": "e112"},
    ]
}))
p = ActionPlan.model_validate(data)
print([(a.action, a.target, a.text) for a in p.actions])
