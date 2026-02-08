import { SessionsSidebar } from '../components/Layout/SessionsSidebar';
import { ChatInterface } from '../components/Chat/ChatInterface';
import { ApprovalDialog } from '../components/ApprovalDialog';
import { AskUserDialog } from '../components/Chat/AskUserDialog';

export function ChatPage() {
  return (
    <div className="h-[calc(100vh-3.5rem)] flex bg-cream">
      {/* Left Sidebar - Sessions */}
      <SessionsSidebar />

      {/* Main Content Area */}
      <main className="flex-1 flex flex-col overflow-hidden bg-white">
        <ChatInterface />
      </main>

      {/* Modals */}
      <ApprovalDialog />
      <AskUserDialog />
    </div>
  );
}
