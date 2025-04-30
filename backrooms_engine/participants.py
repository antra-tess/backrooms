# Placeholder for participant definitions 

import abc
import os
from typing import Dict, Any, Optional, List

# Third-party imports - need to be installed via requirements.txt
import anthropic
import openai

from backrooms_engine.history import ConversationHistory, Message

# Helper to filter out None values from config
def _filter_none_values(config: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in config.items() if v is not None}

class Participant(abc.ABC):
    """Abstract base class for a participant in the backrooms simulation."""
    def __init__(self, name: str, model_config: Dict[str, Any], api_key: Optional[str] = None):
        self.name = name
        self.model_config = model_config # Includes model name, generation params etc.
        self.api_key = api_key
        # Subjective history is handled by ConversationHistory now

    @abc.abstractmethod
    def generate_response(self, history: ConversationHistory, system_prompt: Optional[str] = None) -> str:
        """Generates a response based on the conversation history."""
        pass

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name='{self.name}', model_config={self.model_config})"

class AnthropicParticipant(Participant):
    """Participant using an Anthropic model via the Messages API."""
    def __init__(self, name: str, model_config: Dict[str, Any], api_key: Optional[str] = None):
        super().__init__(name, model_config, api_key)
        api_key = self.api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError(f"API key for Anthropic participant '{self.name}' not provided or found in ANTHROPIC_API_KEY env var.")
        self.client = anthropic.Anthropic(api_key=api_key)
        # Ensure required param is present early (Messages API uses max_tokens)
        if 'max_tokens' not in self.model_config:
             raise ValueError(f"'max_tokens' must be provided in model_config for Anthropic participant '{self.name}'")

    def _format_history_for_anthropic(self, history: ConversationHistory) -> List[Dict[str, str]]:
        """Formats history into the list of message dictionaries for Messages API completion.
        
        The format requires alternating user/assistant roles. For multi-participant,
        we consolidate consecutive turns from 'other' participants into single 'user' turns,
        and represent the current participant's turns as 'assistant'.
        The final message MUST be role:'assistant' to trigger completion.
        """
        messages = []
        history_to_format = history.get_full_history_for_participant(self.name)
        
        current_user_chunk = []
        for msg in history_to_format:
            if msg.participant_name == self.name:
                # If there was a pending user chunk, add it first
                if current_user_chunk:
                    messages.append({"role": "user", "content": "\n".join(current_user_chunk)})
                    current_user_chunk = []
                # Add the assistant message
                messages.append({"role": "assistant", "content": msg.content})
            else:
                # Add to the current user chunk
                current_user_chunk.append(f"{msg.participant_name}: {msg.content}")

        # Add any remaining user chunk
        if current_user_chunk:
             messages.append({"role": "user", "content": "\n".join(current_user_chunk)})
             
        # Ensure the last message is 'assistant' to trigger completion.
        # If the last message in history was 'user', add an empty 'assistant' prompt.
        if not messages or messages[-1]["role"] == "user":
            messages.append({"role": "assistant", "content": ""}) # Start completion
            
        # Note: The specific way subjective history participant names interact 
        # with this formatting might need refinement depending on desired behavior.
        # Currently, a subjective message from 'System' appears like any other participant.
            
        return messages

    def generate_response(self, history: ConversationHistory, system_prompt: Optional[str] = None) -> str:
        formatted_messages = self._format_history_for_anthropic(history)

        # Prepare API parameters, filtering out None values
        api_params = {
            "model": self.model_config.get('model'),
            "system": system_prompt, # Use the dedicated system parameter
            "messages": formatted_messages,
            "max_tokens": self.model_config.get('max_tokens'), # Already validated
            "stop_sequences": self.model_config.get('stop_sequences'),
            "temperature": self.model_config.get('temperature'),
            "top_p": self.model_config.get('top_p'),
            "top_k": self.model_config.get('top_k'),
        }
        filtered_params = _filter_none_values(api_params)

        try:
            # Use messages.create
            completion = self.client.messages.create(**filtered_params)
            # Response is in completion.content, which is a list of blocks
            # Assuming the first block is the text response for now
            if completion.content and isinstance(completion.content, list) and hasattr(completion.content[0], 'text'):
                 return completion.content[0].text.strip()
            else:
                 # Handle cases with no response or unexpected format
                 print(f"Warning: Unexpected Anthropic response format for {self.name}: {completion}")
                 return "(No text content received)"
        except anthropic.APIError as e:
            print(f"Anthropic API error for participant {self.name}: {e}")
            raise

class OpenAIParticipant(Participant):
    """Participant using an OpenAI-compatible API (including OpenAI)."""
    def __init__(self, name: str, model_config: Dict[str, Any], api_key: Optional[str] = None, base_url: Optional[str] = None):
        super().__init__(name, model_config, api_key)
        api_key = self.api_key or os.environ.get("OPENAI_API_KEY")
        # API key is not strictly required if using a local server without auth
        self.client = openai.OpenAI(api_key=api_key, base_url=base_url)

    def _format_history_for_openai(self, history: ConversationHistory, system_prompt: Optional[str]) -> List[Dict[str, str]]:
        """Formats history into the list of message dictionaries."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        history_to_format = history.get_full_history_for_participant(self.name)

        for msg in history_to_format:
            if msg.participant_name == self.name:
                messages.append({"role": "assistant", "content": msg.content})
            else:
                user_content = f'<msg participant="{msg.participant_name}">{msg.content}</msg>'
                messages.append({"role": "user", "content": user_content})
                
        # Ensure messages list is not empty for the API call
        if not messages:
            # Add a minimal user message to start the conversation if history is empty
            messages.append({"role": "user", "content": "(Start of simulation)"})
            
        return messages

    def generate_response(self, history: ConversationHistory, system_prompt: Optional[str] = None) -> str:
        messages = self._format_history_for_openai(history, system_prompt)

        api_params = {
            "model": self.model_config.get('model'),
            "messages": messages,
            "max_tokens": self.model_config.get('max_tokens', self.model_config.get('max_tokens_to_sample')), # Allow max_tokens_to_sample as fallback
            "temperature": self.model_config.get('temperature'),
            "top_p": self.model_config.get('top_p'),
            "frequency_penalty": self.model_config.get('frequency_penalty'),
            "presence_penalty": self.model_config.get('presence_penalty'),
            "stop": self.model_config.get('stop_sequences')
        }
        filtered_params = _filter_none_values(api_params)

        try:
            completion = self.client.chat.completions.create(**filtered_params)
            response = completion.choices[0].message.content
            return response.strip() if response else ""
        except openai.APIError as e:
            print(f"OpenAI API error for participant {self.name}: {e}")
            raise 