"""
ReAct (Reasoning + Acting) Chat Orchestrator

This module implements the ReAct paradigm for AI agents, combining reasoning and acting
in an iterative cycle: Thought → Action → Observation → repeat until final answer.
"""

import asyncio
import json
import logging
import time
from typing import AsyncGenerator, Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum

from fastapi import Request, HTTPException

from fastapi_app.schemas.bot import BotConfigSchema
from fastapi_app.schemas.chat import Message, MessageRole, ToolExecution
from fastapi_app.services.chat.conversation_manager import conversation_manager
from fastapi_app.services.chat.database_service import conversation_db_service
from fastapi_app.core.llm import get_llm_client

logger = logging.getLogger(__name__)


class ReActStage(Enum):
    """ReAct processing stages"""
    THOUGHT = "thought"
    ACTION = "action"
    OBSERVATION = "observation"
    FINAL_ANSWER = "final_answer"


@dataclass
class ToolSelection:
    """Represents a selected tool with its parameters"""
    tool_name: str
    parameters: Dict[str, Any]
    reasoning: Optional[str] = None


@dataclass
class ReActStep:
    """Represents a single step in the ReAct cycle"""
    stage: ReActStage
    content: str
    tool_name: Optional[str] = None
    tool_input: Optional[Dict] = None
    tool_output: Optional[str] = None
    execution_time: Optional[float] = None


def format_sse(event: str, data: Dict) -> str:
    """Format data as Server-Sent Events"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class ReActOrchestrator:
    """
    ReAct (Reasoning + Acting) orchestrator that implements the iterative
    Thought-Action-Observation cycle for intelligent task completion.
    """
    
    def __init__(self):
        self.reasoning_llm_key = "chat_bot_reasoning_llm"
        self.intent_llm_key = "chat_bot_intent_llm"
    
    async def orchestrate_chat(
        self,
        conversation_id: str,
        query: str,
        bot_config: BotConfigSchema,
        request: Request
    ) -> AsyncGenerator[str, None]:
        """
        Orchestrate a complete conversation with initial intent recognition
        
        Args:
            conversation_id: Unique conversation identifier
            query: User's query/question
            bot_config: Bot configuration with tools and prompts
            request: FastAPI request object for disconnect detection
            
        Yields:
            str: SSE-formatted events showing the process
        """
        try:
            # Get conversation history
            session_history = conversation_manager.get_conversation_history(conversation_id)
            
            # Check for client disconnect
            if await request.is_disconnected():
                logger.info(f"Client disconnected during processing: {conversation_id}")
                return
            
            # Step 1: Initial Intent Recognition
            yield format_sse("intent_recognition_start", {
                "message": "Analyzing your question type...",
                "query": query
            })
            
            available_tools = self._get_available_tools(bot_config)
            intent_result = await self._perform_initial_intent_recognition(
                query, session_history, available_tools, bot_config
            )
            
            yield format_sse("intent_recognition_complete", {
                "message": f"Question analysis complete, intent recognition result: {intent_result}",
                "intent": intent_result
            })
            
            # Step 2: Route based on intent
            if intent_result == "CASUAL" or intent_result == "NONE" or not intent_result:
                # Direct conversation - no tools needed
                yield format_sse("direct_conversation_start", {
                    "message": "This is casual conversation, generating response..."
                })
                
                async for event in self._handle_direct_conversation(
                    query, session_history, bot_config, request
                ):
                    yield event
                    
            else:
                # Technical question - use ReAct approach with thought-based tool selection
                yield format_sse("technical_analysis_start", {
                    "message": "This is a technical question, analyzing in depth...",
                    "analysis_type": intent_result
                })
                
                async for event in self._handle_technical_question(
                    query, session_history, intent_result, bot_config, request
                ):
                    yield event
            
            # Save conversation
            await self._save_conversation(conversation_id, query, intent_result)
            
            yield format_sse("conversation_complete", {
                "message": "Conversation complete"
            })
            
        except Exception as e:
            logger.error(f"Error in chat orchestration: {e}")
            yield format_sse("chat_error", {
                "message": f"Some issues occurred during processing: {str(e)}",
                "error": str(e)
            })
    
    async def _thought_phase(
        self,
        query: str,
        session_history: List[Message],
        react_steps: List[ReActStep],
        available_tools: List[str],
        bot_config: BotConfigSchema,
        request: Request
    ) -> ReActStep:
        """Execute the Thought phase of ReAct cycle"""
        
        # Build reasoning prompt
        prompt = await self._build_thought_prompt(
            query, session_history, react_steps, available_tools, bot_config
        )
        
        # Get reasoning LLM
        reasoning_llm = await get_llm_client(self.reasoning_llm_key)
        
        # Generate thought
        thought_content = ""
        async for chunk in reasoning_llm.call_llm_stream(prompt):
            if await request.is_disconnected():
                break
            thought_content = chunk
        
        return ReActStep(
            stage=ReActStage.THOUGHT,
            content=thought_content
        )
    
    async def _action_phase(
        self,
        action_decision: Dict,
        query: str,
        request: Request
    ) -> ReActStep:
        """Execute the Action phase of ReAct cycle"""
        
        tool_name = action_decision.get("tool_name")
        tool_input = action_decision.get("tool_input", {})
        
        start_time = time.time()
        
        # Execute the tool (mock implementation for now)
        tool_output = await self._execute_tool(tool_name, tool_input, query)
        
        execution_time = time.time() - start_time
        
        return ReActStep(
            stage=ReActStage.ACTION,
            content=f"Searching: {tool_name}",
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=tool_output,
            execution_time=execution_time
        )
    
    async def _stream_step(self, step: ReActStep) -> AsyncGenerator[str, None]:
        """Stream a ReAct step as SSE events"""
        
        yield format_sse(f"react_{step.stage.value}_start", {
            "stage": step.stage.value,
            "message": f"Currently {self._get_friendly_stage_name(step.stage)}..."
        })
        
        # Stream content character by character for realistic effect
        for i, char in enumerate(step.content):
            yield format_sse(f"react_{step.stage.value}_chunk", {
                "content": step.content[:i+1],
                "stage": step.stage.value,
                "position": i
            })
            await asyncio.sleep(0.02)  # Control streaming speed
        
        # Include tool information if available
        step_data = {
            "stage": step.stage.value,
            "content": step.content,
            "complete": True
        }
        
        if step.tool_name:
            step_data.update({
                "tool_name": step.tool_name,
                "tool_input": step.tool_input,
                "tool_output": step.tool_output,
                "execution_time": step.execution_time
            })
        
        yield format_sse(f"react_{step.stage.value}_complete", step_data)
    
    # Helper methods would continue...
    
    def _get_available_tools(self, bot_config: BotConfigSchema) -> List[str]:
        """Get list of available tool names from bot config"""
        return [tool.tool_name for tool in bot_config.FunctionCallingModule.Tools_List]
    
    def _get_friendly_stage_name(self, stage: ReActStage) -> str:
        """Get user-friendly name for a ReAct stage"""
        stage_names = {
            ReActStage.THOUGHT: "thinking",
            ReActStage.ACTION: "searching for information",
            ReActStage.OBSERVATION: "analyzing results"
        }
        return stage_names.get(stage, stage.value)
    
    async def _execute_tool(self, tool_name: str, tool_input: Dict, query: str) -> str:
        """Execute a tool and return results"""
        
        try:
            # Simulate tool execution time
            await asyncio.sleep(0.5)
            
            # Real tool execution would go here
            # For now, use mock implementations based on tool name
            if tool_name == "search_knowledge_base":
                return await self._mock_kb_search(query, tool_input)
            elif tool_name == "search_knowledge_graph":
                return await self._mock_kg_search(query, tool_input)
            elif tool_name == "search_8d_reports":
                return await self._mock_8d_search(query, tool_input)
            else:
                return f"Queried {tool_name} with parameters: {tool_input}"
                
        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {e}")
            return f"Encountered issues during query: {str(e)}"
    
    async def _mock_kb_search(self, query: str, tool_input: Dict) -> str:
        """Mock knowledge base search with parameter details"""
        search_terms = tool_input.get("search_terms", query)
        category = tool_input.get("category", "general")
        doc_type = tool_input.get("document_type", "all")
        
        results = f"Knowledge Base Search Results for '{search_terms}' (Category: {category}, Type: {doc_type}):\n"
        results += "- IQC Inspection Standard SOP-Q-001: Quality control procedures for incoming materials\n"
        results += "- Quality Control Process Document QC-P-002: Step-by-step quality assurance workflow\n"
        results += "- Supplier Evaluation Standard SQA-S-003: Criteria and methods for supplier assessment\n"
        results += f"Parameters used: search_terms='{search_terms}', category='{category}', document_type='{doc_type}'"
        
        return results
    
    async def _mock_kg_search(self, query: str, tool_input: Dict) -> str:
        """Mock knowledge graph search with parameter details"""
        entity = tool_input.get("entity", "product")
        relationship_type = tool_input.get("relationship_type", "general")
        depth = tool_input.get("depth", 1)
        
        results = f"Knowledge Graph Search Results for entity '{entity}' (Relationship: {relationship_type}, Depth: {depth}):\n"
        results += "- Suppliers: ABC Company (reliability: 95%), XYZ Manufacturer (reliability: 87%)\n"
        results += "- Related batches: 2024Q1-001 (status: completed), 2024Q1-002 (status: in-progress)\n"
        results += "- Associated parts: P001 (critical), P002 (standard), P003 (optional)\n"
        results += f"Parameters used: entity='{entity}', relationship_type='{relationship_type}', depth={depth}"
        
        return results
    
    async def _mock_8d_search(self, query: str, tool_input: Dict) -> str:
        """Mock 8D reports search with parameter details"""
        issue_type = tool_input.get("issue_type", "quality issue")
        keywords = tool_input.get("keywords", "problem")
        timeframe = tool_input.get("timeframe", "all")
        
        results = f"8D Reports Search Results for '{issue_type}' with keywords '{keywords}' (Timeframe: {timeframe}):\n"
        results += "- 8D-2024-001: Part dimension deviation issue (Root cause: tooling wear, Status: closed)\n"
        results += "- 8D-2024-015: Surface coating defects (Root cause: humidity control, Status: closed)\n"
        results += "- 8D-2024-023: Assembly process improvement (Root cause: procedure update needed, Status: in-progress)\n"
        results += f"Parameters used: issue_type='{issue_type}', keywords='{keywords}', timeframe='{timeframe}'"
        
        return results
    
    async def _perform_initial_intent_recognition(
        self,
        query: str,
        session_history: List[Message],
        available_tools: List[str],
        bot_config: BotConfigSchema
    ) -> str:
        """Perform initial intent recognition on user's raw query"""
        
        # Get intent recognition configuration
        intent_config = bot_config.IntentRecognition
        if not intent_config or not intent_config.prompt_template:
            logger.warning("No intent recognition configuration found, using fallback")
            return "search_knowledge_base"  # Default fallback
        
        # Build tools description
        tools_desc = "\n".join([
            f"- {tool}" for tool in available_tools
        ])
        
        # Build conversation history context
        history_context = ""
        if session_history:
            recent_messages = session_history[-3:]  # Last 3 messages for context
            history_context = "\n".join([
                f"{msg.role.value}: {msg.content}" for msg in recent_messages
            ])
        
        # Format the intent recognition prompt
        prompt = intent_config.prompt_template.format(
            tools_description=tools_desc,
            history_context=history_context,
            query=query
        )
        
        # Get intent recognition LLM
        intent_llm = await get_llm_client(self.intent_llm_key)
        
        # Call LLM for intent recognition
        intent_result = ""
        async for chunk in intent_llm.call_llm_stream(prompt):
            intent_result = chunk
        
        # Clean up the result
        intent_result = intent_result.strip()
        processed_result = self._process_intent_result(intent_result, available_tools)
        
        logger.info(f"Initial intent recognition: '{query}' -> raw: '{intent_result}' -> processed: '{processed_result}'")
        
        return processed_result
    
    def _process_intent_result(self, raw_result: str, available_tools: List[str]) -> str:
        """Process the raw intent recognition result to classify question type"""
        
        # Clean up common formatting
        result = raw_result.strip().replace('。', '').replace('，', ',')
        
        # Check for explicit casual/none indicators
        casual_indicators = ["CASUAL", "NONE", "casual", "chat", "general", "simple", "no tools", "direct answer"]
        if any(indicator in result for indicator in casual_indicators):
            return "CASUAL"
        
        # Check for technical indicators
        technical_indicators = ["TECHNICAL", "technical", "industrial", "quality", "manufacturing", "process", "analysis"]
        if any(indicator in result for indicator in technical_indicators):
            return "TECHNICAL"
        
        # Look for domain-specific keywords that suggest technical nature
        if any(keyword in result for keyword in [
            "knowledge", "standard", "process", "specification", "manual", "procedure",
            "relationship", "graph", "supplier", "batch", "part", "component",
            "8D", "history", "report", "solution", "quality", "defect", "inspection"
        ]):
            return "TECHNICAL"
        
        # Default to technical if uncertain (better to be thorough)
        return "TECHNICAL"
    
    async def _handle_direct_conversation(
        self,
        query: str,
        session_history: List[Message],
        bot_config: BotConfigSchema,
        request: Request
    ) -> AsyncGenerator[str, None]:
        """Handle simple conversations without tools"""
        
        # Use the direct conversation prompt template
        prompt_template = bot_config.AnswerSynthesis.prompt_template_direct_conversation
        if not prompt_template:
            raise ValueError("AnswerSynthesis.prompt_template_direct_conversation is required")
        
        # Build conversation history context
        history_context = ""
        if session_history:
            recent_messages = session_history[-3:]
            history_context = "\n".join([
                f"{msg.role.value}: {msg.content}" for msg in recent_messages
            ])
        
        bot_identity = bot_config.CoreIdentity.DisplayName
        bot_description = getattr(bot_config.CoreIdentity, 'Description', 'AI Assistant')
        
        prompt = prompt_template.format(
            bot_identity=bot_identity,
            bot_description=bot_description,
            query=query,
            history_context=history_context
        )
        
        # Generate direct response
        reasoning_llm = await get_llm_client(self.reasoning_llm_key)
        
        yield format_sse("direct_response_start", {
            "message": "Generating response..."
        })
        
        accumulated_response = ""
        async for chunk in reasoning_llm.call_llm_stream(prompt):
            if await request.is_disconnected():
                break
            
            accumulated_response = chunk
            yield format_sse("direct_response_chunk", {
                "content": chunk,
                "accumulated_length": len(chunk)
            })
            
            await asyncio.sleep(0.01)
        
        yield format_sse("direct_response_complete", {
            "total_length": len(accumulated_response),
            "message": "Response complete"
        })
    
    async def _handle_technical_question(
        self,
        query: str,
        session_history: List[Message],
        intent_result: str,
        bot_config: BotConfigSchema,
        request: Request
    ) -> AsyncGenerator[str, None]:
        """Handle technical questions using ReAct approach with thought-based tool selection"""
        
        available_tools = self._get_available_tools(bot_config)
        
        # Step 1: Thought phase - analyze the problem and determine tool needs
        yield format_sse("thought_start", {
            "message": "Analyzing the problem in depth..."
        })
        
        thought_step = await self._technical_thought_phase(
            query, session_history, available_tools, bot_config, request
        )
        
        # Stream thought process
        async for event in self._stream_step(thought_step):
            yield event
        
        # Step 2: Extract tool selection from thought results
        yield format_sse("tool_selection_start", {
            "message": "Determining which tools to use based on analysis..."
        })
        
        tool_selections = await self._extract_tool_selection_from_thought(
            thought_step.content, available_tools, bot_config, request
        )
        
        tool_names = [ts.tool_name for ts in tool_selections]
        yield format_sse("tool_selection_complete", {
            "message": f"Selected tools: {', '.join(tool_names) if tool_names else 'None'}",
            "selected_tools": tool_names,
            "tool_details": [{"tool": ts.tool_name, "parameters": ts.parameters, "reasoning": ts.reasoning} for ts in tool_selections]
        })
        
        # Step 3: Tool execution (if any tools were selected)
        tool_results = []
        if tool_selections:
            for tool_selection in tool_selections:
                yield format_sse("tool_execution_start", {
                    "message": f"Calling {tool_selection.tool_name} with parameters: {tool_selection.parameters}...",
                    "tool": tool_selection.tool_name,
                    "parameters": tool_selection.parameters
                })
                
                action_step = await self._action_phase(
                    {"tool_name": tool_selection.tool_name, "tool_input": tool_selection.parameters}, 
                    query, request
                )
                
                # Stream action process
                async for event in self._stream_step(action_step):
                    yield event
                
                tool_results.append(action_step.tool_output)
        
        # Step 4: Generate final answer with tool results
        yield format_sse("final_synthesis_start", {
            "message": "Integrating information to generate final answer..."
        })
        
        async for event in self._generate_technical_answer(
            query, session_history, tool_results, bot_config, request
        ):
            yield event
    
    async def _technical_thought_phase(
        self,
        query: str,
        session_history: List[Message],
        available_tools: List[str],
        bot_config: BotConfigSchema,
        request: Request
    ) -> ReActStep:
        """Execute thought phase for technical questions"""
        
        # Build reasoning prompt for technical analysis
        prompt = await self._build_technical_thought_prompt(
            query, session_history, available_tools, bot_config
        )
        
        # Get reasoning LLM
        reasoning_llm = await get_llm_client(self.reasoning_llm_key)
        
        # Generate thought
        thought_content = ""
        async for chunk in reasoning_llm.call_llm_stream(prompt):
            if await request.is_disconnected():
                break
            thought_content = chunk
        
        return ReActStep(
            stage=ReActStage.THOUGHT,
            content=thought_content
        )
    
    async def _extract_tool_selection_from_thought(
        self,
        thought_content: str,
        available_tools: List[str],
        bot_config: BotConfigSchema,
        request: Request
    ) -> List[ToolSelection]:
        """Extract tool selection with parameters from thought phase results using LLM"""
        
        # Build detailed tool descriptions with parameter examples
        tools_desc = self._build_tool_descriptions_with_parameters(available_tools)
        
        # Use a specific prompt for tool selection with parameters
        tool_selection_prompt = f"""Based on the following analysis, determine which tools (if any) should be used to answer the user's question, and specify the exact parameters for each tool.

Analysis from thought phase:
{thought_content}

Available tools with their parameters:
{tools_desc}

Instructions:
- If no tools are needed (the analysis shows we can answer directly), respond with "NONE"
- If tools are needed, provide them in JSON format with specific parameters
- Only select tools that are actually needed based on the analysis
- Generate specific, relevant parameters based on the analysis content

Expected JSON format for tool selection:
```json
[
  {{
    "tool_name": "search_knowledge_base",
    "parameters": {{
      "search_terms": "specific keywords from analysis",
      "category": "quality_standards"
    }},
    "reasoning": "why this tool with these parameters is needed"
  }},
  {{
    "tool_name": "search_knowledge_graph",
    "parameters": {{
      "entity": "specific entity to search",
      "relationship_type": "supplier_relationship"
    }},
    "reasoning": "why this tool with these parameters is needed"
  }}
]
```

Tool selection with parameters:"""

        # Get LLM for tool selection
        reasoning_llm = await get_llm_client(self.reasoning_llm_key)
        
        # Get tool selection decision
        tool_selection_result = ""
        async for chunk in reasoning_llm.call_llm_stream(tool_selection_prompt):
            if await request.is_disconnected():
                break
            tool_selection_result = chunk
        
        # Process the result
        return self._process_tool_selection_with_parameters(tool_selection_result.strip(), available_tools)
    
    def _process_tool_selection_result(self, selection_result: str, available_tools: List[str]) -> List[str]:
        """Process the tool selection result and return valid tool names"""
        
        # Clean up the result
        result = selection_result.strip().replace('。', '').replace('，', ',')
        
        # Check for NONE indicators
        if "NONE" in result.upper() or "none" in result.lower():
            return []
        
        # Extract tool names
        selected_tools = []
        for tool in available_tools:
            if tool in result:
                selected_tools.append(tool)
        
        # If no specific tools found, try to parse comma-separated list
        if not selected_tools:
            # Split by comma and check each part
            parts = [part.strip() for part in result.split(',')]
            for part in parts:
                for tool in available_tools:
                    if tool in part:
                        selected_tools.append(tool)
                        break
        
        # Remove duplicates while preserving order
        return list(dict.fromkeys(selected_tools))
    
    def _build_tool_descriptions_with_parameters(self, available_tools: List[str]) -> str:
        """Build detailed tool descriptions with parameter specifications"""
        
        tool_specs = {
            "search_knowledge_base": {
                "description": "Search quality manuals, standards, and process documents",
                "parameters": {
                    "search_terms": "str - Specific keywords or phrases to search for",
                    "category": "str - Optional category filter (quality_standards, procedures, manuals)",
                    "document_type": "str - Optional type filter (SOP, manual, standard)"
                }
            },
            "search_knowledge_graph": {
                "description": "Search relationships between entities (suppliers, parts, batches, etc.)",
                "parameters": {
                    "entity": "str - Primary entity to search for (product name, supplier, part number)",
                    "relationship_type": "str - Type of relationship to explore (supplier_relationship, part_dependency, batch_traceability)",
                    "depth": "int - Search depth for relationships (default: 1)"
                }
            },
            "search_8d_reports": {
                "description": "Search historical 8D problem-solving reports",
                "parameters": {
                    "issue_type": "str - Type of issue to search for (quality_defect, process_issue, supplier_problem)",
                    "keywords": "str - Specific keywords related to the problem",
                    "timeframe": "str - Optional time filter (recent, last_quarter, last_year)"
                }
            }
        }
        
        descriptions = []
        for tool in available_tools:
            if tool in tool_specs:
                spec = tool_specs[tool]
                param_desc = "\n    ".join([f"- {k}: {v}" for k, v in spec["parameters"].items()])
                descriptions.append(f"**{tool}**:\n  Description: {spec['description']}\n  Parameters:\n    {param_desc}")
            else:
                descriptions.append(f"**{tool}**: General purpose tool")
        
        return "\n\n".join(descriptions)
    
    def _process_tool_selection_with_parameters(self, selection_result: str, available_tools: List[str]) -> List[ToolSelection]:
        """Process the tool selection result with parameters and return ToolSelection objects"""
        
        # Check for NONE indicators
        if "NONE" in selection_result.upper() or "none" in selection_result.lower():
            return []
        
        try:
            # Try to extract JSON from the result
            json_start = selection_result.find('[')
            json_end = selection_result.rfind(']') + 1
            
            if json_start >= 0 and json_end > json_start:
                json_str = selection_result[json_start:json_end]
                tool_data = json.loads(json_str)
                
                tool_selections = []
                for item in tool_data:
                    tool_name = item.get("tool_name", "")
                    if tool_name in available_tools:
                        tool_selections.append(ToolSelection(
                            tool_name=tool_name,
                            parameters=item.get("parameters", {}),
                            reasoning=item.get("reasoning", "")
                        ))
                
                return tool_selections
                
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"Failed to parse JSON tool selection: {e}, falling back to simple parsing")
        
        # Fallback: simple parsing for tool names
        fallback_tools = []
        for tool in available_tools:
            if tool in selection_result:
                # Extract basic parameters from context
                parameters = self._extract_basic_parameters_from_context(tool, selection_result)
                fallback_tools.append(ToolSelection(
                    tool_name=tool,
                    parameters=parameters,
                    reasoning=f"Extracted from context mention of {tool}"
                ))
        
        return fallback_tools
    
    def _extract_basic_parameters_from_context(self, tool_name: str, context: str) -> Dict[str, Any]:
        """Extract basic parameters for a tool from the context when JSON parsing fails"""
        
        # Basic parameter extraction based on tool type
        if tool_name == "search_knowledge_base":
            return {
                "search_terms": "quality standards procedures",
                "category": "general"
            }
        elif tool_name == "search_knowledge_graph":
            return {
                "entity": "product",
                "relationship_type": "general"
            }
        elif tool_name == "search_8d_reports":
            return {
                "issue_type": "quality_issue",
                "keywords": "problem analysis"
            }
        
        return {}
    
    async def _build_technical_thought_prompt(
        self,
        query: str,
        session_history: List[Message],
        available_tools: List[str],
        bot_config: BotConfigSchema
    ) -> str:
        """Build prompt for technical thought phase"""
        
        # Use configured ReAct thought prompt but simplified
        if not bot_config.OrchestrationLogic.react_thought_prompt:
            # Fallback prompt
            tools_desc = "\n".join([f"- {tool}" for tool in available_tools])
            return f"""Analyze this technical question in depth: {query}

Available tools for information gathering:
{tools_desc}

Please provide a thorough analysis that covers:
1. What is the core problem or question being asked?
2. What specific information would be needed to provide a complete answer?
3. What knowledge gaps exist that might require external data sources?
4. What type of information would be most valuable (standards, historical data, relationships, etc.)?

Focus on understanding the question deeply and identifying what information would be needed to provide the best possible answer."""
        
        # Prepare context
        tools_desc = "\n".join([f"- {tool}" for tool in available_tools])
        
        # Build conversation history
        history_context = ""
        if session_history:
            recent_messages = session_history[-3:]
            history_context = "\n".join([
                f"{msg.role.value}: {msg.content}" for msg in recent_messages
            ])
        
        # Format the configured prompt
        return bot_config.OrchestrationLogic.react_thought_prompt.format(
            tools_description=tools_desc,
            query=query,
            history_context=history_context,
            previous_steps=""  # No previous steps in this simplified approach
        )
    
    async def _generate_technical_answer(
        self,
        query: str,
        session_history: List[Message],
        tool_results: List[str],
        bot_config: BotConfigSchema,
        request: Request
    ) -> AsyncGenerator[str, None]:
        """Generate final answer for technical questions using tool results"""
        
        # Build context from tool results
        context = ""
        for i, result in enumerate(tool_results):
            if result:
                context += f"Tool query result {i+1}:\n{result}\n\n"
        
        # Use configured prompt template
        prompt_template = bot_config.AnswerSynthesis.prompt_template_with_tools
        if not prompt_template:
            raise ValueError("AnswerSynthesis.prompt_template_with_tools is required")
        
        # Build conversation history
        history_context = ""
        if session_history:
            recent_messages = session_history[-3:]
            history_context = "\n".join([
                f"{msg.role.value}: {msg.content}" for msg in recent_messages
            ])
        
        bot_identity = bot_config.CoreIdentity.DisplayName
        bot_description = getattr(bot_config.CoreIdentity, 'Description', 'AI Assistant')
        
        prompt = prompt_template.format(
            bot_identity=bot_identity,
            bot_description=bot_description,
            query=query,
            history_context=history_context,
            context_parts=context
        )
        
        # Generate final answer
        reasoning_llm = await get_llm_client(self.reasoning_llm_key)
        
        yield format_sse("technical_answer_start", {
            "message": "Generating final answer..."
        })
        
        accumulated_response = ""
        async for chunk in reasoning_llm.call_llm_stream(prompt):
            if await request.is_disconnected():
                break
            
            accumulated_response = chunk
            yield format_sse("technical_answer_chunk", {
                "content": chunk,
                "accumulated_length": len(chunk)
            })
            
            await asyncio.sleep(0.01)
        
        yield format_sse("technical_answer_complete", {
            "total_length": len(accumulated_response),
            "message": "Technical analysis complete"
        })
    
    async def _save_conversation(
        self,
        conversation_id: str,
        user_query: str,
        intent_result: str
    ) -> None:
        """Save conversation to database and memory"""
        
        try:
            # Save user message
            user_message = Message(
                role=MessageRole.USER,
                content=user_query
            )
            conversation_manager.add_message(conversation_id, user_message)
            
            await conversation_db_service.save_message(
                conversation_id=conversation_id,
                role=MessageRole.USER.value,
                content=user_query
            )
            
            # Create summary content based on intent
            if intent_result == "CASUAL" or intent_result == "NONE":
                content = "Had casual conversation"
            else:
                content = "Analyzed technical question using ReAct approach with thought-based tool selection"
            
            assistant_message = Message(
                role=MessageRole.ASSISTANT,
                content=content
            )
            conversation_manager.add_message(conversation_id, assistant_message)
            
            await conversation_db_service.save_message(
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT.value,
                content=content,
                metadata={
                    "intent_result": intent_result,
                    "conversation_type": "casual" if intent_result in ["CASUAL", "NONE"] else "technical",
                    "approach": "direct_response" if intent_result in ["CASUAL", "NONE"] else "react_with_thought_based_tools"
                }
            )
            
        except Exception as e:
            logger.error(f"Error saving conversation: {e}")


# Global instance
react_orchestrator = ReActOrchestrator()