/**
 * Stylist chat client — MOCK / NOT BACKED.
 *
 * The Chat tab is an AI stylist that "knows the closet". There is no backend
 * conversational endpoint yet. sendStylistMessage() returns a canned, local
 * reply so the UI is fully interactive. When a real endpoint exists (e.g.
 * POST /stylist/chat), replace the body below with a fetch + Bearer auth.
 */

export interface ChatMessage {
  id: string;
  from: 'user' | 'ai';
  text: string;
  /** Optional closet item ids the AI attached as an outfit suggestion. */
  outfit?: string[];
}

const CANNED_REPLIES = [
  'Your linen shirt with the chelsea boots reads sharp but relaxed. Layer the camel coat if it cools off.',
  'For that, I’d pair your white tee with the black jeans and white sneakers — clean and easy.',
  'Try the beige cardigan over the linen shirt. Neutral, weather-ready, and it works with what you own.',
];

let replyIndex = 0;

/**
 * Send a message to the stylist and get a reply. Mock: returns a rotating canned
 * response after a short delay. `history` is accepted for forward-compat.
 */
export async function sendStylistMessage(
  _text: string,
  _history: ChatMessage[] = []
): Promise<ChatMessage> {
  await new Promise((r) => setTimeout(r, 550));
  const text = CANNED_REPLIES[replyIndex % CANNED_REPLIES.length];
  replyIndex += 1;
  return {
    id: `ai-${replyIndex}-${text.length}`,
    from: 'ai',
    text,
    // Attach a sample outfit on the first reply only.
    outfit: replyIndex === 1 ? undefined : undefined,
  };
}
