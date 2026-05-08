import Layout from '../../components/Layout';
import ChatInterface from '../../components/ChatInterface';

export default function StudentChat() {
  return (
    <Layout title="AI Study Assistant">
      <div className="h-[calc(100vh-8rem)]">
        <ChatInterface role="student" />
      </div>
    </Layout>
  );
}
