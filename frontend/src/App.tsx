import { useStore } from "./store";
import LoginScreen from "./components/LoginScreen";
import ChatScreen from "./components/ChatScreen";

export default function App() {
  const authed = useStore((s) => s.authed);
  return authed ? <ChatScreen /> : <LoginScreen />;
}
