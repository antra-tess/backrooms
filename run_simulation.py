# Placeholder for example simulation script 

import os
import dotenv
from typing import List, Dict, Optional

from backrooms_engine.engine import SimulationEngine
from backrooms_engine.participants import AnthropicParticipant, OpenAIParticipant
from backrooms_engine.history import Message, ConversationHistory

def main():
    """Configures and runs a sample backrooms simulation."""
    # Load environment variables from .env file if it exists
    dotenv.load_dotenv()

    # --- Configuration --- 

    # 1. System Prompt (Optional)
    # This prompt is shown to all participants (if supported by their API format)
    system_prompt = "You are participants in a simulation. Discuss the nature of consciousness."

    # 2. Participants Configuration
    participants = [
        AnthropicParticipant(
            name="Claude Opus",
            model_config={
                "model": "claude-3-opus-20240229",
                "max_tokens": 300, # Use max_tokens for Messages API
                "temperature": 1,
            },
            # API key will be read from ANTHROPIC_API_KEY env var by default
            # api_key="sk-..."
        ),
        OpenAIParticipant(
            name="4o",
            model_config={
                "model": "chatgpt-4o-latest",
                "max_tokens": 300,
                "temperature": 1,
            },
            # API key will be read from OPENAI_API_KEY env var by default
            # api_key="sk-...",
            # base_url="http://localhost:8000/v1" # Optional: for local/custom endpoints
        ),
        # Add more participants as needed
    ]

    # 3. Subjective Histories (Optional)
    # Provide private initial context/instructions to specific participants
    subjective_histories = {
        "Claude Opus": [
            {"participant_name": "System", "content": "Focus on the philosophical aspects."},
        ],
        "4o": [
            {"participant_name": "System", "content": "Focus on the neuroscientific perspectives."},
        ]
    }

    # 4. Simulation Parameters
    max_turns = 6
    turn_delay_seconds = 1 # Optional delay between turns

    # 5. Callback Function (Optional)
    def stop_on_keyword(message: Message, history: ConversationHistory) -> bool:
        """Stop simulation if the word 'shutdown' is detected."""
        if "shutdown" in message.content.lower():
            print(f"Callback triggered: Detected 'shutdown' in message from {message.participant_name}. Stopping simulation.")
            return True
        return False

    # --- Simulation Setup --- 

    print("Initializing Simulation Engine...")
    engine = SimulationEngine(
        participants=participants,
        max_turns=max_turns,
        system_prompt=system_prompt,
        on_message_callback=stop_on_keyword,
        turn_delay_seconds=turn_delay_seconds
    )

    # Set subjective histories before running
    for name, history_data in subjective_histories.items():
        engine.history.set_subjective_history(name, history_data)
        print(f"Set subjective history for {name}")

    # --- Run Simulation --- 
    print("\nStarting Simulation...")
    final_history = engine.run()

    print("\nSimulation Complete.")
    # Final history is also logged to output.log
    # You can access the final state via the `final_history` variable
    # print(f"\nFinal Transcript:\n{final_history}")

if __name__ == "__main__":
    main() 