"""Chat with the HR / Healthcare / Finance assistants. The supervisor picks the domain."""
import uuid

from langchain_core.messages import HumanMessage

from graph import graph


def main() -> None:
    config = {"configurable": {"thread_id": uuid.uuid4().hex}}
    print("Vertical assistants: HR, Healthcare, Finance. Type 'exit' to quit.\n")
    while True:
        try:
            text = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if text.lower() in {"exit", "quit"}:
            break
        if not text:
            continue
        try:
            result = graph.invoke({"messages": [HumanMessage(text)]}, config)
            print(f"[{result['domain']}] {result['messages'][-1].content}\n")
        except Exception as e:
            print(f"[error] {e}\n")


if __name__ == "__main__":
    main()
