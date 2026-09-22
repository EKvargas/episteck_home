/* eslint-disable @typescript-eslint/no-explicit-any */
'use client';

import React from 'react';
import { 
  AssistantRuntimeProvider, 
  useLocalRuntime,
  ThreadPrimitive,
  MessagePrimitive,
  ComposerPrimitive
} from '@assistant-ui/react';
import { CaretCircleUp } from '@phosphor-icons/react';
import styles from './AskScreen.module.css';
import { useAppContext } from '@/components/providers/AppProvider';

// A mock tool UI for Nutrition
function NutritionSummaryTool() {
  return (
    <div className={styles.toolNutrition}>
      <span className={styles.toolNutritionTitle}>Nutrition today</span>
      <span className={styles.toolNutritionData}>1,200 / 2,000 kcal</span>
      <span className={styles.toolNutritionDetail}>Protein remaining: 42 g</span>
      <button style={{ alignSelf: 'flex-start', padding: '6px 12px', marginTop: '4px', borderRadius: '4px', background: 'var(--olin-accent)', color: 'var(--olin-bg-canvas)', border: 'none', cursor: 'pointer', fontSize: '0.9rem' }}>
        View nutrition
      </button>
    </div>
  );
}

function MyUserMessage() {
  return (
    <MessagePrimitive.Root>
      <div className={`${styles.messageRow} ${styles.messageUser}`}>
        <div className={`${styles.messageBubble} ${styles.messageBubbleUser}`}>
          <MessagePrimitive.Content />
        </div>
      </div>
    </MessagePrimitive.Root>
  );
}

function MyAssistantMessage() {
  const contentComponents: any = {
    Text: (props: any) => <p style={{ margin: 0 }}>{props.part.text}</p>,
    ToolCall: (props: any) => {
      if (props.part.toolName === 'nutrition_summary') {
        return <NutritionSummaryTool />;
      }
      return null;
    }
  };

  return (
    <MessagePrimitive.Root>
      <div className={`${styles.messageRow} ${styles.messageAssistant}`}>
        <div className={`${styles.messageBubble} ${styles.messageBubbleAssistant}`}>
          <MessagePrimitive.Content components={contentComponents} />
        </div>
      </div>
    </MessagePrimitive.Root>
  );
}

export function AskOlin() {
  const { activeContext } = useAppContext();
  
  // @ts-expect-error - Bypass strict ChatModelAdapter type for spike
  const runtime = useLocalRuntime(async (message: any) => {
    // Check if the user is asking about nutrition
    if (message.content?.[0]?.text?.toLowerCase().includes('protein')) {
      return {
        content: [
          { type: 'text', text: "You have about 42 g remaining based on today's plan." },
          { type: 'tool-call', toolName: 'nutrition_summary', toolCallId: 'call_1', args: {} }
        ]
      };
    }

    // Generic response
    return {
      content: [{ type: 'text', text: "I'm Olin. How can I help you and your family today?" }]
    };
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div className={styles.container}>
        <div className={styles.header}>
          <h1 className={styles.title}>Ask Olin</h1>
          <span className={styles.contextSubtitle}>
            Viewing {activeContext.name} · {activeContext.mode === 'PERSONAL' ? 'You' : (activeContext.mode === 'FAMILY' ? 'Family overview' : 'Shared with you')}
          </span>
        </div>

        <ThreadPrimitive.Root className={styles.threadContainer}>
          <ThreadPrimitive.Viewport style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '24px' }}>
            <ThreadPrimitive.Empty>
              <div style={{ margin: 'auto', color: 'var(--olin-text-muted)', textAlign: 'center' }}>
                Start a conversation...
              </div>
            </ThreadPrimitive.Empty>
            
            <ThreadPrimitive.Messages
              components={{
                UserMessage: MyUserMessage,
                AssistantMessage: MyAssistantMessage,
              }}
            />
          </ThreadPrimitive.Viewport>

          <div className={styles.composerContainer}>
            <ComposerPrimitive.Root className={styles.composerForm}>
              <ComposerPrimitive.Input 
                className={styles.composerInput}
                placeholder="Ask Olin anything..."
                autoFocus
              />
              <ComposerPrimitive.Send asChild>
                <button className={styles.composerSubmit}>
                  <CaretCircleUp size={24} weight="fill" />
                </button>
              </ComposerPrimitive.Send>
            </ComposerPrimitive.Root>
          </div>
        </ThreadPrimitive.Root>
      </div>
    </AssistantRuntimeProvider>
  );
}
