# Backrooms Engine

A research platform for autonomous LLM interactions without human participation.

## Overview

Backrooms Engine enables multiple LLM models to interact with each other in a controlled environment, facilitating research into emergent behaviors, alignment, and multi-agent systems. Models from different providers (Anthropic, OpenAI) can participate in the same conversation with configurable parameters.

## Core Features

- **Multi-Model Conversations**: Create simulations with models from different providers (Claude, GPT-4, etc.)
- **Subjective Histories**: Configure different context for each participant
- **Streaming Interface**: Watch conversations unfold in real-time
- **Persistent Storage**: Save configurations and transcripts for later analysis
- **Web Application**: User-friendly UI for configuration and monitoring
- **User Authentication**: Secure access with account protection

## Implementation

- **Engine**: Python-based core with modular participant classes
- **API Support**: 
  - Anthropic (Claude models using Messages API)
  - OpenAI (GPT models using Chat Completions API)
- **Web Interface**: Flask application with real-time SSE streaming
- **Security**: Password hashing and permission controls

## Getting Started

1. Clone this repository
2. Install dependencies: `pip install -r requirements.txt`
3. Create a `.env` file with your API keys:
   ```
   ANTHROPIC_API_KEY=your_key_here
   OPENAI_API_KEY=your_key_here
   FLASK_SECRET_KEY=random_secret_key
   ADMIN_PASSWORD=your_admin_password
   ```
4. Start the web server: `python web_app/app.py`
5. Access the interface at http://localhost:5033
6. Log in with username `admin` and your configured password

## Usage

1. Configure a new simulation with:
   - System prompt (optional)
   - Maximum number of turns
   - Turn delay (optional)
   - Multiple participants with model types, names, and parameters
   - Optional subjective history for each participant
2. Run the simulation and watch the conversation unfold in real-time
3. Access saved simulations from the "My Simulations" page

## Advanced Features

- **Custom Prompting**: Configure specialized instructions for each agent
- **Memory Control**: Define what each participant can "remember" from the conversation
- **Streaming Output**: Monitor conversations as they develop in real-time
- **Experiment Replay**: Review past conversations exactly as they occurred 