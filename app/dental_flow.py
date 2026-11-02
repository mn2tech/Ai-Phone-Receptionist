"""Dental appointment request collection flow for Techne Dental."""

from typing import Optional

# Dental appointment collection steps (not demo steps)
DENTAL_APPOINTMENT_STEPS = [
    "name",
    "phone",
    "new_or_existing",
    "reason",
    "insurance",
    "preferred_times",
]


def get_next_dental_prompt(state: dict) -> Optional[str]:
    """
    Return the next question for dental appointment collection.
    
    Returns None when all fields are collected.
    """
    prompts = {
        "name": "May I have your name please?",
        "phone": "What is the best phone number to reach you?",
        "new_or_existing": "Are you a new patient or an existing patient?",
        "reason": "What is the reason for your visit? For example, cleaning, exam, toothache, or another concern.",
        "insurance": "Do you have dental insurance? If so, what is the name of your insurance plan?",
        "preferred_times": "What days and times work best for you? For example, weekday mornings, afternoons, or specific days.",
    }
    
    for step in DENTAL_APPOINTMENT_STEPS:
        if step not in state or not state[step]:
            return prompts.get(step, "Could you repeat that please?")
    
    return None


def process_dental_input(state: dict, speech: str) -> dict:
    """
    Store the caller's answer in the current dental collection step.
    
    Returns updated state dict.
    """
    for step in DENTAL_APPOINTMENT_STEPS:
        if step not in state or not state[step]:
            value = speech.strip()
            
            # Skip optional fields
            if step == "insurance" and value.lower() in ("skip", "no", "none", "n/a", "no insurance"):
                value = "No insurance"
            
            state[step] = value
            break
    
    return state


def is_dental_collection_complete(state: dict) -> bool:
    """Check whether all required dental appointment fields have been collected."""
    for step in DENTAL_APPOINTMENT_STEPS:
        if step not in state or not state[step]:
            return False
    return True


def dental_complete_message(state: dict) -> str:
    """Return confirmation message after dental collection is done."""
    name = state.get("name", "there")
    return (
        f"Thank you, {name}. I've sent your appointment request to the team. "
        "They will call you on the next business day to confirm your appointment. "
        "Is there anything else I can help with?"
    )
