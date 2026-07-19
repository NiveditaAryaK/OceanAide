from state import Agent
from retrieval import load_cards

def main():
    cards = load_cards()
    agent = Agent(cards)
    print("Ocean Node (offline). Type a log. Ctrl+C to exit.")
    while True:
        try:
            user = input("\n> ")
            if not user.strip():
                continue
            out = agent.step(user)
            print("\n" + out)
        except (KeyboardInterrupt, EOFError):
            break
        except Exception as e:
            print(f"\n[error] {e} — session continues, try again.")

if __name__ == "__main__":
    main()
