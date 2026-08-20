import re

with open('social_agent/graph/nodes.py', 'r') as f:
    orig = f.read()

decorator_code = """
import time
from functools import wraps

def node_telemetry(node_name: str, model_name: str = "llama3.3:70b-instruct"):
    def decorator(func):
        @wraps(func)
        async def wrapper(state: SocialAgentState) -> Dict[str, Any]:
            campaign_id = state.get("campaign_id", "default_campaign")
            thread_id = state.get("thread_id", f"thread_{campaign_id}")
            
            # Circuit Breaker Cost Check
            if not cost_tracker.check_budget_clearance(campaign_id, estimated_tokens=1000):
                logger.error(f"Budget exceeded for {campaign_id}. Aborting {node_name}.")
                return {"error_logs": ["Budget exceeded. Aborted."]}
                
            async with trace_span(f"node.{node_name}", {"campaign_id": campaign_id, "thread_id": thread_id}) as span:
                start_time = time.time()
                try:
                    result = await func(state)
                    latency = time.time() - start_time
                    
                    # Estimate tokens from result
                    p_tok = len(str(state)) // 4
                    c_tok = len(str(result)) // 4
                    
                    usage = cost_tracker.record_step_usage(
                        campaign_id=campaign_id,
                        node_name=node_name,
                        model_name=model_name,
                        prompt_tokens=p_tok,
                        completion_tokens=c_tok,
                        latency_seconds=latency
                    )
                    
                    span.set_attribute("social_agent.latency", latency)
                    span.set_attribute("social_agent.cost", usage.cost_usd)
                    
                    return result
                except Exception as e:
                    span.record_exception(e)
                    raise
        return wrapper
    return decorator

"""

# Insert decorator code after the imports/instantiations
insert_idx = orig.find('async def plan_research_node')
if insert_idx != -1 and 'def node_telemetry' not in orig:
    new_code = orig[:insert_idx] + decorator_code + orig[insert_idx:]
    
    # Now replace the function definitions to add decorators
    new_code = new_code.replace(
        'async def plan_research_node(state: SocialAgentState) -> Dict[str, Any]:',
        '@node_telemetry("plan_research", "qwen2.5:32b-instruct")\nasync def plan_research_node(state: SocialAgentState) -> Dict[str, Any]:'
    )
    new_code = new_code.replace(
        'async def act_research_and_draft_node(state: SocialAgentState) -> Dict[str, Any]:',
        '@node_telemetry("act_research_and_draft")\nasync def act_research_and_draft_node(state: SocialAgentState) -> Dict[str, Any]:'
    )
    new_code = new_code.replace(
        'async def media_prep_node(state: SocialAgentState) -> Dict[str, Any]:',
        '@node_telemetry("media_prep", "llama3.2:11b-vision")\nasync def media_prep_node(state: SocialAgentState) -> Dict[str, Any]:'
    )
    new_code = new_code.replace(
        'async def evaluate_audit_node(state: SocialAgentState) -> Dict[str, Any]:',
        '@node_telemetry("evaluate_audit")\nasync def evaluate_audit_node(state: SocialAgentState) -> Dict[str, Any]:'
    )
    new_code = new_code.replace(
        'async def reflect_remedy_node(state: SocialAgentState) -> Dict[str, Any]:',
        '@node_telemetry("reflect_remedy")\nasync def reflect_remedy_node(state: SocialAgentState) -> Dict[str, Any]:'
    )
    new_code = new_code.replace(
        'async def hitl_gate_node(state: SocialAgentState) -> Dict[str, Any]:',
        '@node_telemetry("hitl_gate")\nasync def hitl_gate_node(state: SocialAgentState) -> Dict[str, Any]:'
    )
    new_code = new_code.replace(
        'async def publish_dispatch_node(state: SocialAgentState) -> Dict[str, Any]:',
        '@node_telemetry("publish_dispatch", "mistral-small:24b")\nasync def publish_dispatch_node(state: SocialAgentState) -> Dict[str, Any]:'
    )
    
    with open('social_agent/graph/nodes.py', 'w') as f:
        f.write(new_code)
