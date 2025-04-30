# Placeholder for simulation engine class 

import time
import logging
from typing import List, Optional, Callable, Any, Iterator

from backrooms_engine.participants import Participant
from backrooms_engine.history import ConversationHistory, Message

# Basic logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log_file_handler = logging.FileHandler("output.log")
log_file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger = logging.getLogger(__name__)
logger.addHandler(log_file_handler)

class SimulationEngine:
    """Orchestrates the backrooms simulation."""
    def __init__(
        self,
        participants: List[Participant],
        max_turns: int,
        system_prompt: Optional[str] = None,
        # Callback signature: (message: Message, history: ConversationHistory) -> bool (True to stop)
        on_message_callback: Optional[Callable[[Message, ConversationHistory], bool]] = None,
        turn_delay_seconds: float = 0 # Optional delay between turns
    ):
        if not participants:
            raise ValueError("At least one participant is required.")
        self.participants = participants
        self.max_turns = max_turns
        self.system_prompt = system_prompt
        self.on_message_callback = on_message_callback
        self.turn_delay_seconds = turn_delay_seconds
        self.history = ConversationHistory()

    def run(self) -> Iterator[Message]:
        """Runs the simulation loop, yielding each message as it's generated."""
        logger.info(f"Starting simulation run (generator) for {self.max_turns} turns.")
        if self.system_prompt:
            logger.info(f"System Prompt: {self.system_prompt}")

        num_participants = len(self.participants)
        turn_count = 0
        simulation_halted = False

        try:
            while turn_count < self.max_turns:
                participant_index = turn_count % num_participants
                current_participant = self.participants[participant_index]

                logger.info(f"\n--- Turn {turn_count + 1}: {current_participant.name}'s turn --- Generating...")

                response_content = "(Error occurred)" # Default in case of early break
                try:
                    response_content = current_participant.generate_response(
                        self.history, 
                        self.system_prompt
                    )
                    if not response_content:
                        logger.warning(f"{current_participant.name} produced an empty response.")
                        response_content = "(No response)"

                except Exception as e:
                    logger.error(f"FATAL: Error during {current_participant.name}'s turn: {e}", exc_info=True)
                    logger.warning("Halting simulation due to error.")
                    simulation_halted = True
                    # Yield an error message before stopping
                    error_message = Message(participant_name="System", content=f"ERROR: Halting simulation. {current_participant.name} failed: {e}")
                    yield error_message
                    self.history.add_message(error_message.participant_name, error_message.content) # Add error to history too
                    break # Stop the loop

                # Create and yield the new message
                new_message = Message(participant_name=current_participant.name, content=response_content)
                self.history.add_message(new_message.participant_name, new_message.content)
                
                log_line = f"{new_message.participant_name}: {new_message.content}"
                logger.info(log_line) # Log the message
                # print(log_line) # Printing to console might be less useful now, handled by web UI
                
                yield new_message # Yield the message for the stream

                # Call callback if defined (Check if it should stop the simulation)
                should_stop = False
                if self.on_message_callback:
                    try:
                        should_stop = self.on_message_callback(new_message, self.history)
                    except Exception as e:
                        logger.error(f"Error in on_message_callback: {e}", exc_info=True)
                
                if should_stop:
                    logger.info("Simulation stopped early by callback.")
                    simulation_halted = True
                    # Yield a final system message indicating callback stop
                    stop_message = Message(participant_name="System", content="STOP: Simulation ended by callback condition.")
                    yield stop_message
                    self.history.add_message(stop_message.participant_name, stop_message.content)
                    break

                turn_count += 1

                if self.turn_delay_seconds > 0 and turn_count < self.max_turns:
                     time.sleep(self.turn_delay_seconds)

        except KeyboardInterrupt:
            logger.warning("Simulation interrupted by user.")
            simulation_halted = True
            yield Message(participant_name="System", content="STOP: Simulation interrupted by user.")

        finally:
            log_end_message = "Simulation run ended" 
            if simulation_halted:
                log_end_message += " prematurely."
            else:
                log_end_message += " normally."
                yield Message(participant_name="System", content="END: Simulation finished normally.")
            
            logger.info(log_end_message)
            logger.info(f"\n--- Final Transcript ({turn_count} turns processed) written to log ---\n{self.history}")
            # No return value needed for generator

        return self.history 