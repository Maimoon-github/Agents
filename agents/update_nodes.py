import re

with open('social_agent/graph/nodes.py', 'r') as f:
    content = f.read()

# Add imports
if 'from social_agent.telemetry.tracing import trace_span' not in content:
    content = content.replace(
        'from social_agent.memory.session_manager import SessionManager',
        'from social_agent.memory.session_manager import SessionManager\nfrom social_agent.telemetry.tracing import trace_span\nfrom social_agent.telemetry.cost_tracker import CostTracker'
    )
if 'cost_tracker = CostTracker()' not in content:
    content = content.replace(
        'session_manager = SessionManager()',
        'session_manager = SessionManager()\ncost_tracker = CostTracker()'
    )

with open('social_agent/graph/nodes.py', 'w') as f:
    f.write(content)
