import os
import dotenv
from flask import Flask, render_template, request, redirect, url_for, flash, Response, stream_with_context, abort
from flask_login import (
    LoginManager, UserMixin, login_required, login_user, logout_user, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash
import sys
import uuid
import json
import time
from typing import Dict, List
import datetime

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
DEFAULT_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'password') # Get from env or default
users = {
    "1": User(id="1", username="admin", password_hash=generate_password_hash(DEFAULT_PASSWORD))
}
if DEFAULT_PASSWORD == 'password':
    print(f"\n *** WARNING: Using default admin password 'password'. Set ADMIN_PASSWORD env var. *** \n")
else:
    print(f"\n Admin user 'admin' initialized. Use the password set in ADMIN_PASSWORD env var. \n")

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

# --- Constants & Setup ---
SIMULATIONS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'simulations'))

# Ensure simulations directory exists
if not os.path.exists(SIMULATIONS_DIR):
    try:
        os.makedirs(SIMULATIONS_DIR)
        print(f"Created simulations directory: {SIMULATIONS_DIR}")
    except OSError as e:
        print(f"Error creating simulations directory {SIMULATIONS_DIR}: {e}", file=sys.stderr)
        # Depending on severity, might want to exit or handle differently

# --- Helper Function --- 
def format_log_line(name: str, content: str) -> str:
    return f"{name}: {content}\n"

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
    """Handles form submission, saves config to file, redirects to stream view."""
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
        simulation_data = {
            'id': sim_id,
            'user_id': current_user.id, # Associate with current user
            'timestamp': time.time(), # Store creation time
            'participants_config': participants_config,
            'max_turns': max_turns,
            'system_prompt': system_prompt,
            'turn_delay_seconds': turn_delay
        }
        
        # Save configuration to JSON file
        config_path = os.path.join(SIMULATIONS_DIR, f"{sim_id}.json")
        try:
            with open(config_path, 'w') as f:
                json.dump(simulation_data, f, indent=4)
            app.logger.info(f"Saved simulation config: {config_path}")
        except IOError as e:
             flash(f"Error saving simulation configuration: {e}", "error")
             app.logger.error(f"Failed to save config {config_path}: {e}")
             return redirect(url_for('index'))

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
    # Check if config file exists, otherwise it was likely invalid/not saved
    config_path = os.path.join(SIMULATIONS_DIR, f"{simulation_id}.json")
    if not os.path.exists(config_path):
        app.logger.warning(f"Attempted to view stream for non-existent config: {simulation_id}")
        flash("Error: Simulation configuration not found.", "error")
        return redirect(url_for('index'))
    # We don't need to load the full config here anymore, just render the page
    return render_template('stream.html', simulation_id=simulation_id)

@app.route('/stream/<simulation_id>')
@login_required # Protect this route
def stream(simulation_id):
    """Server-Sent Events endpoint: loads config, runs engine, streams & logs messages."""
    config_path = os.path.join(SIMULATIONS_DIR, f"{simulation_id}.json")
    log_path = os.path.join(SIMULATIONS_DIR, f"{simulation_id}.log")

    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
    except (IOError, json.JSONDecodeError) as e:
        app.logger.error(f"Failed to load config {config_path}: {e}")
        # Return an error event in the stream
        def error_stream():
             error_data = json.dumps({"error": f"Failed to load simulation config: {e}"})
             yield f"event: error\ndata: {error_data}\n\n"
        return Response(stream_with_context(error_stream()), mimetype='text/event-stream')

    # Check ownership (although redundant if file system perms were used)
    if config.get('user_id') != current_user.id:
        app.logger.warning(f"User {current_user.id} tried to stream simulation {simulation_id} owned by {config.get('user_id')}")
        def error_stream():
             error_data = json.dumps({"error": "Permission denied to stream this simulation."})
             yield f"event: error\ndata: {error_data}\n\n"
        return Response(stream_with_context(error_stream()), mimetype='text/event-stream')

    def generate_events():
        log_file = None
        try:
            log_file = open(log_path, 'w')
            app.logger.info(f"Opened log file {log_path} for simulation {simulation_id}")

            # --- Instantiate Participants (from loaded config) --- 
            participants: List[Participant] = []
            subjective_histories = {}
            for p_data in config['participants_config']:
                model_name = p_data['model']
                model_config = p_data['model_config']
                name = p_data['name']
                participant_class = MODEL_TO_CLASS.get(model_name)
                if not participant_class:
                    raise ValueError(f"Model '{model_name}' not found in mapping during stream generation.")
                
                try:
                    participants.append(participant_class(name=name, model_config=model_config))
                except ValueError as ve:
                     raise ValueError(f"Failed to init participant {name}: {ve}") # Raise to be caught below
                     
                if p_data['subjective_history']:
                    subjective_histories[name] = p_data['subjective_history']
            
            # --- Setup and Run Engine --- 
            engine = SimulationEngine(
                participants=participants,
                max_turns=config['max_turns'],
                system_prompt=config['system_prompt'],
                turn_delay_seconds=config['turn_delay_seconds']
            )
            
            for name, history_data in subjective_histories.items():
                engine.history.set_subjective_history(name, history_data)
            
            start_content = f"Simulation {simulation_id} starting...\nSystem Prompt: {config['system_prompt'] or 'None'}\nMax Turns: {config['max_turns']}\n---\n"
            start_data = json.dumps({"name": "System", "content": start_content})
            yield f"event: message\ndata: {start_data}\n\n"
            log_file.write(format_log_line("System", start_content))
            time.sleep(0.1)
            
            for message in engine.run():
                message_data = json.dumps({"name": message.participant_name, "content": message.content})
                yield f"event: message\ndata: {message_data}\n\n"
                log_file.write(format_log_line(message.participant_name, message.content))
            
            app.logger.info(f"Event stream finished normally for simulation ID: {simulation_id}")
            log_file.write(format_log_line("System", "--- Simulation Ended Normally ---"))

        except Exception as e:
             error_text = f"Stream/Run failed: {e}"
             app.logger.error(f"Event stream failed for simulation ID: {simulation_id}: {error_text}", exc_info=True)
             error_data = json.dumps({"error": error_text})
             yield f"event: error\ndata: {error_data}\n\n"
             if log_file:
                 try:
                     log_file.write(format_log_line("System", f"--- ERROR: {error_text} ---"))
                 except Exception as log_err:
                     app.logger.error(f"Failed to write final error to log {log_path}: {log_err}")
        finally:
            if log_file:
                try:
                    log_file.close()
                    app.logger.info(f"Closed log file {log_path}")
                except IOError as e:
                    app.logger.error(f"Error closing log file {log_path}: {e}")
            # Don't delete config file anymore
            app.logger.info(f"Closing event stream connection for simulation ID: {simulation_id}")

    return Response(stream_with_context(generate_events()), mimetype='text/event-stream')

# --- New Routes for Viewing Past Simulations ---

@app.route('/simulations')
@login_required
def list_simulations():
    """Lists simulations created by the current user."""
    user_simulations = []
    try:
        for filename in os.listdir(SIMULATIONS_DIR):
            if filename.endswith('.json'):
                sim_id = filename[:-5] # Remove .json
                config_path = os.path.join(SIMULATIONS_DIR, filename)
                try:
                    with open(config_path, 'r') as f:
                        config = json.load(f)
                    
                    # Check ownership
                    if config.get('user_id') == current_user.id:
                        # Format timestamp nicely
                        ts = config.get('timestamp', 0)
                        dt_object = datetime.datetime.fromtimestamp(ts)
                        formatted_time = dt_object.strftime("%Y-%m-%d %H:%M:%S")
                        
                        # Get participant names
                        p_names = [p.get('name', 'Unknown') for p in config.get('participants_config', [])]
                        
                        user_simulations.append({
                            'id': sim_id,
                            'timestamp': ts, # Keep original for sorting
                            'formatted_time': formatted_time,
                            'participants': ", ".join(p_names)
                        })
                except (IOError, json.JSONDecodeError, KeyError) as e:
                    app.logger.warning(f"Could not load or parse simulation config {config_path}: {e}")
                    continue # Skip corrupted/invalid files
        
        # Sort by timestamp, newest first
        user_simulations.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
        
    except OSError as e:
        app.logger.error(f"Error listing simulations directory {SIMULATIONS_DIR}: {e}")
        flash(f"Error accessing simulation history: {e}", "error")
        
    return render_template('simulations.html', simulations=user_simulations)

@app.route('/simulation/<simulation_id>')
@login_required
def view_simulation(simulation_id):
    """Displays the config and transcript log for a specific simulation."""
    config_path = os.path.join(SIMULATIONS_DIR, f"{simulation_id}.json")
    log_path = os.path.join(SIMULATIONS_DIR, f"{simulation_id}.log")
    config = None
    transcript = "(Log file not found or could not be read)"
    
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
    except (IOError, json.JSONDecodeError) as e:
        app.logger.error(f"Failed to load config for view {config_path}: {e}")
        abort(404, description="Simulation configuration not found or invalid.")

    # Check ownership
    if config.get('user_id') != current_user.id:
        app.logger.warning(f"User {current_user.id} tried to view simulation {simulation_id} owned by {config.get('user_id')}")
        abort(403, description="Permission denied to view this simulation.")
        
    # Try to read the log file
    try:
        with open(log_path, 'r') as f:
            transcript = f.read()
    except IOError as e:
         app.logger.warning(f"Could not read log file {log_path}: {e}")
         # transcript keeps its default error message

    # Format timestamp for display
    ts = config.get('timestamp', 0)
    dt_object = datetime.datetime.fromtimestamp(ts)
    config['formatted_time'] = dt_object.strftime("%Y-%m-%d %H:%M:%S")
         
    return render_template('view_simulation.html', config=config, transcript=transcript)

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