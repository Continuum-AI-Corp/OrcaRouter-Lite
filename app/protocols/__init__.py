"""Native-protocol adapters (Anthropic Messages API, Gemini generateContent).

Each module translates its wire format to/from the internal OpenAI format
consumed by the shared chat engine (`app.routes.chat.execute_chat`). The
translators are pure functions / pure async transformers so they unit-test
without an app or mocks. See PLAN-NATIVE-PROTOCOLS.md.
"""
