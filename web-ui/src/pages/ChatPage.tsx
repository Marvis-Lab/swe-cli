import { SessionsSidebar } from '../components/Layout/SessionsSidebar';
import { ChatInterface } from '../components/Chat/ChatInterface';
import { ApprovalDialog } from '../components/ApprovalDialog';
import { AskUserDialog } from '../components/Chat/AskUserDialog';

export function ChatPage() {
  return (
    <div className="h-screen flex bg-bg-100">
      {/* Left Sidebar - Sessions */}
      <SessionsSidebar />

      {/* Main Content Area */}
      <main className="flex-1 flex flex-col overflow-hidden bg-bg-000">
        <ChatInterface />
      </main>

      {/* Modals */}
      <ApprovalDialog />
      <AskUserDialog />
    </div>
  );
}
