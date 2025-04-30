from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

@dataclass
class Message:
    participant_name: str
    content: str

@dataclass
class ConversationHistory:
    messages: List[Message] = field(default_factory=list)
    subjective_histories: Dict[str, List[Message]] = field(default_factory=dict)

    def add_message(self, participant_name: str, content: str):
        self.messages.append(Message(participant_name=participant_name, content=content))

    def get_full_history_for_participant(self, participant_name: str) -> List[Message]:
        """Retrieves the combined subjective and main history for a participant."""
        subjective = self.subjective_histories.get(participant_name, [])
        return subjective + self.messages

    def set_subjective_history(self, participant_name: str, history_data: List[Dict[str, str]]):
        """Sets the subjective history from a list of dicts.

        Args:
            participant_name: The name of the participant.
            history_data: A list of dictionaries, e.g., 
                          [{'participant_name': 'sys', 'content': 'Secret info'}, ...]
        """
        self.subjective_histories[participant_name] = [
            Message(participant_name=item['participant_name'], content=item['content'])
            for item in history_data
        ]

    def get_last_message(self) -> Optional[Message]:
        return self.messages[-1] if self.messages else None

    def __str__(self) -> str:
        return "\n".join([f"{msg.participant_name}: {msg.content}" for msg in self.messages]) 