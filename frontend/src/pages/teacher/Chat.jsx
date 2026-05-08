import Layout from '../../components/Layout';
import ChatInterface from '../../components/ChatInterface';

export default function TeacherChat() {
  return (
    <Layout title="AI Teaching Assistant">
      <div className="h-[calc(100vh-8rem)]">
        <ChatInterface role="teacher" />
      </div>
    </Layout>
  );
}
