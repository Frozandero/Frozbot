from google.genai import errors, types
from google.genai.types import Tool, UrlContext
from google import genai

import asyncio
import concurrent.futures
from typing import Optional
import os

URL_CONTEXT_TOOL = Tool(url_context=UrlContext())  # type: ignore
GEMINI_CLIENT = genai.Client() if os.getenv("GEMINI_API_KEY") else None


def get_gemini_client():
    global GEMINI_CLIENT
    if not GEMINI_CLIENT:
        GEMINI_CLIENT = genai.Client()
    return GEMINI_CLIENT


async def try_gemini_models(
    question: str, context_string: str, media_parts: Optional[list]
) -> Optional[str]:
    """
    Try to get a response from Gemini using multiple models with fallback.
    Returns the response text if successful, None if all models fail with quota errors.
    """
    if not GEMINI_CLIENT:
        return None

    # Define models to try in order of preference
    models_to_try = [
        "gemini-3-flash",  # Newest and bestest
        "gemini-2.5-pro",  # Best quality, highest quota
        "gemini-2.5-flash",  # Good quality, medium quota
        "gemini-2.5-flash-lite",  # Basic quality, highest quota
        "gemini-2.0-flash",  # Good quality, medium quota
        "gemini-2.0-flash-lite",  # Basic quality, highest quota
    ]

    tools_for_supporting_models = [URL_CONTEXT_TOOL]
    thinking_budgets = [512, 512, 256, 0, 0, 0]  # 6 models
    tools = [
        tools_for_supporting_models,  # gemini-3-flash
        tools_for_supporting_models,  # gemini-2.5-pro
        tools_for_supporting_models,  # gemini-2.5-flash
        tools_for_supporting_models,  # gemini-2.5-flash-lite
        tools_for_supporting_models,  # gemini-2.0-flash
        [],  # gemini-2.0-flash-lite
    ]

    for i, (model_name, thinking_budget) in enumerate(
        zip(models_to_try, thinking_budgets)
    ):
        try:
            print(f"🔄 Trying model: {model_name} (attempt {i+1}/{len(models_to_try)})")

            # Run the Gemini API call in a thread to avoid blocking the event loop
            def call_gemini_api():
                if not GEMINI_CLIENT:
                    raise RuntimeError("Gemini client not initialized")
                request_contents = [*media_parts, question] if media_parts else question
                return GEMINI_CLIENT.models.generate_content(
                    model=model_name,
                    config=types.GenerateContentConfig(
                        system_instruction=context_string,  # type: ignore
                        thinking_config=types.ThinkingConfig(
                            thinking_budget=thinking_budget
                        ),
                        tools=tools[i],
                        temperature=0.9,  # Add variability to prevent repetitive responses
                    ),
                    contents=request_contents,
                )

            # Use ThreadPoolExecutor to run the blocking API call
            loop = asyncio.get_event_loop()
            with concurrent.futures.ThreadPoolExecutor() as executor:
                response = await asyncio.wait_for(
                    loop.run_in_executor(executor, call_gemini_api),
                    timeout=30.0,  # 30 second timeout
                )

            print(f"✅ Success with model: {model_name}")

            # Check if response has text attribute
            if hasattr(response, "text") and response.text:
                return response.text
            else:
                print(
                    f"⚠️ Warning: {model_name} returned response without text attribute"
                )
                print(f"Response object type: {type(response)}")
                if hasattr(response, "text"):
                    print(f"Response.text value: {response.text}")
                continue

        except asyncio.TimeoutError:
            print(f"⏰ Timeout for {model_name}, trying next model...")
            continue
        except errors.APIError as e:
            if e.code == 429:
                print(f"⏰ Quota exceeded for {model_name}, trying next model...")
                continue
            elif e.code in [
                500,
                502,
                503,
                504,
            ]:  # Server errors that might be temporary
                print(f"🔄 Server error ({e.code}) for {model_name}, retrying...")
                # For server errors, try the same model again once
                try:
                    print(f"🔄 Retrying {model_name} after server error...")
                    # Add a small delay before retry to avoid overwhelming the service
                    await asyncio.sleep(1)

                    # Define the retry function inline to avoid scope issues
                    def retry_gemini_api():
                        if not GEMINI_CLIENT:
                            raise RuntimeError("Gemini client not initialized")
                        request_contents_retry = (
                            [*media_parts, question] if media_parts else question
                        )
                        return GEMINI_CLIENT.models.generate_content(
                            model=model_name,
                            config=types.GenerateContentConfig(
                                system_instruction=context_string,  # type: ignore
                                thinking_config=types.ThinkingConfig(
                                    thinking_budget=thinking_budget
                                ),
                                temperature=0.9,  # Add variability to prevent repetitive responses
                            ),
                            contents=request_contents_retry,
                        )

                    loop = asyncio.get_event_loop()
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        response = await asyncio.wait_for(
                            loop.run_in_executor(executor, retry_gemini_api),
                            timeout=30.0,
                        )
                    print(f"✅ Success with {model_name} on retry")

                    # Check if response has text attribute
                    if hasattr(response, "text") and response.text:
                        return response.text
                    else:
                        print(
                            f"⚠️ Warning: {model_name} retry returned response without text attribute"
                        )
                        print(f"Response object type: {type(response)}")
                        print(f"Response object attributes: {dir(response)}")
                        if hasattr(response, "text"):
                            print(f"Response.text value: {response.text}")
                        continue
                except Exception as retry_error:
                    print(
                        f"❌ Retry failed for {model_name}: {str(retry_error)[:100]}..."
                    )
                    continue
            else:
                # Non-quota, non-server error, log and try next model
                error_msg = e.message if e.message else str(e)
                print(
                    f"❌ Non-quota error with {model_name}: {error_msg[:100]}... (code: {e.code})"
                )
                continue
        except Exception as e:
            print(f"❌ Unexpected error with {model_name}: {str(e)[:100]}...")
            # Log the full error for debugging
            import traceback

            print(f"Full error details for {model_name}:")
            traceback.print_exc()
            continue

    # All models failed
    print("🚫 All models failed")
    print(f"Failed to get response for question: {question[:100]}...")

    # Log additional debugging information
    print("🔍 Debugging info:")
    print(f"  - Total models attempted: {len(models_to_try)}")
    print(f"  - GEMINI_CLIENT initialized: {GEMINI_CLIENT is not None}")
    if GEMINI_CLIENT:
        print(f"  - GEMINI_CLIENT type: {type(GEMINI_CLIENT)}")

    return None


async def summarize_messages_with_gemini(serialized_messages: str) -> Optional[str]:
    """Summarize a set of messages into 1–2 sentences using the existing Gemini client with model fallback."""
    if not GEMINI_CLIENT:
        return None
    context_instr = (
        "You are summarizing a Discord channel's recent conversation for an assistant. "
        "Compress only. Do not speculate. Keep it to 1–2 sentences, focusing on the main topics, decisions, or questions. "
        "Include notable entities or links if critical."
    )
    prompt = (
        "Summarize the following messages in at most 2 sentences."
        "\n\nMessages:\n" + serialized_messages
    )
    try:
        return await try_gemini_models(prompt, context_instr, None)
    except Exception as e:
        print(f"Error summarizing messages: {e}")
        return None
