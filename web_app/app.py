import os
import dotenv
from flask import Flask, render_template, request, redirect, url_for, flash, Response, stream_with_context
from flask_login import (
    LoginManager, UserMixin, login_required, login_user, logout_user, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash
import sys
import uuid
import json
import time
from typing import Dict, List

# Add the parent directory to sys.path to find backrooms_engine
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backrooms_engine.engine import SimulationEngine
from backrooms_engine.participants import AnthropicParticipant, OpenAIParticipant, Participant
from backrooms_engine.history import Message, ConversationHistory

# Load environment variables
dotenv.load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

# Define the app globally
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', os.urandom(24)) # Use env var or random

# --- Flask-Login Setup ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login' # Redirect here if @login_required fails
login_manager.login_message_category = "error" # Use our CSS category

# Simple User Model (In-memory)
class User(UserMixin):
    def __init__(self, id, username, password_hash):
        self.id = id
        self.username = username
        self.password_hash = password_hash

# WARNING: Hardcoded user store - replace with database for production!
# Generate a hash for the password 'password' (replace with a strong password)
DEFAULT_PASSWORD = 'password' 
users = {
    "1": User(id="1", username="admin", password_hash=generate_password_hash(DEFAULT_PASSWORD))
}
print(f"\n *** WARNING: Using hardcoded user 'admin' with password '{DEFAULT_PASSWORD}' *** \n")

@login_manager.user_loader
def load_user(user_id):
    return users.get(user_id)

# --- Model Mapping --- 
# Maps known model names to their participant class
# Add more models as needed
MODEL_TO_CLASS = {
    # Newer Anthropic Models (from user request)
    "claude-3-7-sonnet-20250219": AnthropicParticipant,
    "claude-3-5-sonnet-20241022": AnthropicParticipant, # v2
    "claude-3-5-sonnet-20240620": AnthropicParticipant, # v1
    "claude-3-5-haiku-20241022": AnthropicParticipant,
    
    # Older Anthropic Models
    "claude-3-opus-20240229": AnthropicParticipant,
    "claude-3-sonnet-20240229": AnthropicParticipant,
    "claude-3-haiku-20240307": AnthropicParticipant,
    "claude-2.1": AnthropicParticipant,
    "claude-2.0": AnthropicParticipant,
    "claude-instant-1.2": AnthropicParticipant,
    # OpenAI Models
    "gpt-4o": OpenAIParticipant,
    "gpt-4o-mini": OpenAIParticipant,
    "gpt-4-turbo": OpenAIParticipant,
    "gpt-4": OpenAIParticipant,
    "gpt-3.5-turbo": OpenAIParticipant,
    "chatgpt-4o-latest": OpenAIParticipant, # alias for gpt-4o
    "gpt-4.1": OpenAIParticipant, # Hypothetical/future?
    "o1": OpenAIParticipant, # Assuming maps to an OpenAI model
    "o1-mini": OpenAIParticipant,
    "o3": OpenAIParticipant,
    "o3-mini": OpenAIParticipant,
    "o4-mini": OpenAIParticipant, # Alias for gpt-4o-mini?
    
    # Add other OpenAI-compatible models here if known
    # "local-model/llama-3-70b-instruct": OpenAIParticipant, 
}

# In-memory storage for simulation configurations (temporary)
# In a real app, use Redis, a database, or a proper task queue
simulation_configs: Dict[str, Dict] = {}
# We don't store full results anymore, streaming directly

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        # Find user (simple iteration for in-memory store)
        user = None
        for u in users.values():
            if u.username == username:
                user = u
                break
        
        if user and check_password_hash(user.password_hash, password):
            login_user(user, remember=request.form.get('remember'))
            flash('Logged in successfully.', 'success')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))
        else:
            flash('Invalid username or password.', 'error')
            
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))

@app.route('/')
@login_required # Protect this route
def index():
    """Displays the configuration form."""
    # Sort model names for better UX in the dropdown
    sorted_model_names = sorted(list(MODEL_TO_CLASS.keys()))
    return render_template('index.html', model_names=sorted_model_names)

@app.route('/run', methods=['POST'])
@login_required # Protect this route
def run_simulation_setup():
    """Handles form submission, stores config, redirects to stream view."""
    try:
        system_prompt = request.form.get('system_prompt')
        max_turns = int(request.form.get('max_turns', 10))
        turn_delay = float(request.form.get('turn_delay', 0))

        participants_config = [] # Store config dicts, not instantiated objects
        i = 0
        while True:
            pmodel = request.form.get(f'participants[{i}][model]')
            if not pmodel:
                break
            pname = request.form.get(f'participants[{i}][name]', f'Participant_{i+1}')
            pmax_tokens = int(request.form.get(f'participants[{i}][max_tokens]', 300))
            ptemp = float(request.form.get(f'participants[{i}][temperature]', 1.0))
            psubjective = request.form.get(f'participants[{i}][subjective_history]', '')
            
            subjective_list = []
            if psubjective:
                 for line in psubjective.strip().split('\n'):
                     if ':' in line:
                        role, content = line.split(':', 1)
                        subjective_list.append({'participant_name': role.strip(), 'content': content.strip()})
                     else:
                         subjective_list.append({'participant_name': 'System', 'content': line.strip()})
            
            # Basic validation before storing config
            participant_class = MODEL_TO_CLASS.get(pmodel)
            if participant_class is None:
                 flash(f"Error: Model '{pmodel}' is not recognized.", "error")
                 return redirect(url_for('index'))
            if participant_class == AnthropicParticipant and not pmax_tokens:
                 flash(f"Error: 'Max Tokens' is required for Anthropic model '{pmodel}' (participant '{pname}').", "error")
                 return redirect(url_for('index'))
                 
            participants_config.append({
                'model': pmodel,
                'name': pname,
                'model_config': {
                    'model': pmodel,
                    'max_tokens': pmax_tokens,
                    'temperature': ptemp
                },
                 'subjective_history': subjective_list
            })
            i += 1

        if not participants_config:
             flash("Error: At least one participant is required.", "error")
             return redirect(url_for('index'))

        # Generate a unique ID for this simulation
        sim_id = str(uuid.uuid4())
        
        # Store the configuration needed to run the simulation later
        simulation_configs[sim_id] = {
            'participants_config': participants_config,
            'max_turns': max_turns,
            'system_prompt': system_prompt,
            'turn_delay_seconds': turn_delay
        }
        
        app.logger.info(f"Simulation config stored for ID: {sim_id}")

        # Redirect to the page that will display the stream
        return redirect(url_for('stream_view', simulation_id=sim_id))

    except Exception as e:
        flash(f"An error occurred during setup: {e}", "error")
        app.logger.error("Error during simulation setup:", exc_info=True)
        return redirect(url_for('index'))

@app.route('/stream_view/<simulation_id>')
@login_required # Protect this route
def stream_view(simulation_id):
    """Displays the page that will connect to the SSE stream."""
    # Check if config exists, maybe pass some initial info?
    if simulation_id not in simulation_configs:
        flash("Error: Simulation ID not found or expired.", "error")
        return redirect(url_for('index'))
    config = simulation_configs[simulation_id]
    return render_template('stream.html', simulation_id=simulation_id, config=config)

@app.route('/stream/<simulation_id>')
@login_required # Protect this route
def stream(simulation_id):
    """Server-Sent Events endpoint to stream simulation messages."""
    config = simulation_configs.get(simulation_id)

    if not config:
        # Return an empty response or an error event?
        def error_stream():
             yield f"event: error\ndata: Simulation config not found for ID {simulation_id}\n\n"
        return Response(error_stream(), mimetype='text/event-stream')

    def generate_events():
        try:
            app.logger.info(f"Starting event stream for simulation ID: {simulation_id}")
            # --- Instantiate Participants --- 
            participants: List[Participant] = []
            subjective_histories = {}
            for p_data in config['participants_config']:
                model_name = p_data['model']
                model_config = p_data['model_config']
                name = p_data['name']
                participant_class = MODEL_TO_CLASS[model_name] # Assumes valid model checked in setup
                
                try:
                    participants.append(participant_class(name=name, model_config=model_config))
                except ValueError as ve:
                     # Log and yield error event
                     error_data = json.dumps({"error": f"Failed to init {name}: {ve}"})
                     yield f"event: error\ndata: {error_data}\n\n"
                     app.logger.error(f"Stream Error (Init): {ve} for {name}")
                     return # Stop the stream
                     
                if p_data['subjective_history']:
                    subjective_histories[name] = p_data['subjective_history']
            
            # --- Setup and Run Engine --- 
            engine = SimulationEngine(
                participants=participants,
                max_turns=config['max_turns'],
                system_prompt=config['system_prompt'],
                turn_delay_seconds=config['turn_delay_seconds']
                # Add callback if needed later
            )
            
            # Set subjective histories
            for name, history_data in subjective_histories.items():
                engine.history.set_subjective_history(name, history_data)
            
            # Yield initial message
            start_data = json.dumps({"name": "System", "content": f"Simulation {simulation_id} starting..."})
            yield f"event: message\ndata: {start_data}\n\n"
            time.sleep(0.1) # Small delay to ensure client connects
            
            # Iterate through the generator
            for message in engine.run():
                message_data = json.dumps({"name": message.participant_name, "content": message.content})
                # Standard SSE message format
                yield f"event: message\ndata: {message_data}\n\n"
                # Optional: Add a small delay between messages for better UX?
                # time.sleep(0.05)
                
            # Signal completion (optional, client can also detect stream close)
            # end_data = json.dumps({"name": "System", "content": "Stream finished."}) 
            # yield f"event: end_stream\ndata: {end_data}\n\n"
            app.logger.info(f"Event stream finished normally for simulation ID: {simulation_id}")

        except Exception as e:
             # Log and yield error event
             error_data = json.dumps({"error": f"Stream failed: {e}"})
             yield f"event: error\ndata: {error_data}\n\n"
             app.logger.error(f"Event stream failed for simulation ID: {simulation_id}", exc_info=True)
        finally:
            # Clean up the stored configuration once the stream ends (success or fail)
            if simulation_id in simulation_configs:
                del simulation_configs[simulation_id]
                app.logger.info(f"Cleaned up config for simulation ID: {simulation_id}")
            app.logger.info(f"Closing event stream for simulation ID: {simulation_id}")

    # Return the streaming response
    return Response(stream_with_context(generate_events()), mimetype='text/event-stream')

if __name__ == '__main__':
    app_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Configure the existing global app instance
    app.template_folder = os.path.join(app_dir, 'templates')
    app.static_folder = os.path.join(app_dir, 'static')
    # app.secret_key is already set globally

    print(f"Parent directory added to sys.path: {os.path.abspath(os.path.join(app_dir, '..'))}")
    dotenv_path = os.path.join(app_dir, '..', '.env')
    print(f"Attempting to load .env from: {dotenv_path}")
    # Load dotenv again here? Or rely on the global load? Let's ensure it's loaded.
    dotenv.load_dotenv(dotenv_path=dotenv_path, override=True) 

    # Add basic logging for Flask
    if not app.debug:
        import logging
        from logging.handlers import RotatingFileHandler
        log_path = os.path.join(app_dir, '..', 'webapp.log') 
        file_handler = RotatingFileHandler(log_path, maxBytes=10240, backupCount=10)
        file_handler.setFormatter(logging.Formatter(
             '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
        ))
        file_handler.setLevel(logging.INFO)
        # Clear existing handlers before adding?
        # for handler in app.logger.handlers[:]:
        #     app.logger.removeHandler(handler)
        if not app.logger.handlers: # Add handler only if none exist
            app.logger.addHandler(file_handler)
            app.logger.setLevel(logging.INFO)
            app.logger.info('Web App startup - Logging configured.')
        else:
            app.logger.info('Web App startup - Logger already configured.')

    # Run the configured global app, listening on all interfaces
    app.run(host='0.0.0.0', port=5033, debug=True) # debug=True allows auto-reloading 