// src/components/features/AskOlinModal.tsx
'use client';

import React, { useState, useRef, useEffect } from 'react';
import { 
  X, 
  ArrowUp, 
  Sparkle, 
  Brain, 
  CaretDown, 
  CaretUp, 
  Heartbeat, 
  ArrowRight 
} from '@phosphor-icons/react';
import Link from 'next/link';
import styles from './AskOlinModal.module.css';

interface Message {
  id: string;
  sender: 'user' | 'agent';
  text: string;
  hasPersonalization?: boolean;
}

interface AskOlinModalProps {
  isOpen: boolean;
  onClose: () => void;
  initialQuery?: string;
  onLockDoor?: () => void;
}

export function AskOlinModal({
  isOpen,
  onClose,
  initialQuery = '',
  onLockDoor,
}: AskOlinModalProps) {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: 'm-0',
      sender: 'agent',
      text: "Good afternoon. I'm monitoring the Vargas home context, Ana's upcoming clinic return at 15:00, and your nutrition logs. How can I help?",
    },
  ]);
  const [customInput, setCustomInput] = useState<string | null>(null);
  const [expandedExplanationId, setExpandedExplanationId] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const chatStreamRef = useRef<HTMLDivElement>(null);

  const inputText = customInput !== null ? customInput : initialQuery;

  useEffect(() => {
    if (isOpen) {
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  }, [isOpen]);

  useEffect(() => {
    if (chatStreamRef.current) {
      chatStreamRef.current.scrollTop = chatStreamRef.current.scrollHeight;
    }
  }, [messages]);

  if (!isOpen) return null;

  const handleSend = (textToSend?: string) => {
    const text = (textToSend !== undefined ? textToSend : inputText).trim();
    if (!text) return;

    const userMsg: Message = {
      id: `u-${Date.now()}`,
      sender: 'user',
      text,
    };

    setMessages((prev) => [...prev, userMsg]);
    setCustomInput('');

    setTimeout(() => {
      let reply = 'Context noted in Vargas Household state. Hermes has synchronized this with your daily schedule.';
      const lower = text.toLowerCase();

      if (lower.includes('lock')) {
        onLockDoor?.();
        reply = 'I have commanded the Home Assistant gateway to lock the smart deadbolt. Front door is now Locked.';
      } else if (lower.includes('ana') || lower.includes('appointment')) {
        reply = "Ana's appointment with Dr. Weber is underway. Estimated departure is 15:00. I'll ping the Family display when her car departs.";
      } else if (lower.includes('nutrition') || lower.includes('lunch') || lower.includes('dinner')) {
        reply = "Logged nutrition update to Erick's health ledger via Nutrition domain service.";
      } else if (lower.includes('grocery') || lower.includes('checklist')) {
        reply = 'Wild Baked Salmon checklist: Fresh salmon fillet (600g), organic asparagus bundle, Meyer lemons. Added to Mealie cart.';
      } else if (lower.includes('timer') || lower.includes('countdown')) {
        reply = 'Dinner prep countdown initialized: 17:45 preheat oven, 18:00 roast asparagus, 18:30 dinner ready.';
      } else if (lower.includes('suggest') && lower.includes('dinner')) {
        reply = 'I suggest Seared Mediterranean Salmon with Asparagus and Quinoa (560 kcal). Fits your 2,000 kcal target, respects your fresh fish preference, and finishes before 19:00.';
      }

      const isDinnerSuggestion = lower.includes('suggest') && lower.includes('dinner');
      const agentMsgId = `a-${Date.now()}`;

      const agentMsg: Message = {
        id: agentMsgId,
        sender: 'agent',
        text: reply,
        hasPersonalization: isDinnerSuggestion,
      };

      setMessages((prev) => [...prev, agentMsg]);
      if (isDinnerSuggestion) {
        // Automatically expand explanation so user sees the distinction immediately
        setExpandedExplanationId(agentMsgId);
      }
    }, 450);
  };

  const toggleExplanation = (msgId: string) => {
    setExpandedExplanationId((prev) => (prev === msgId ? null : msgId));
  };

  return (
    <div
      role="dialog"
      aria-labelledby="ask-olin-title"
      className={styles.modal}
    >
      <div className={styles.modalHeader}>
        <div className={styles.headerLeft}>
          <div className={styles.brandDot} aria-hidden="true">
            O
          </div>
          <div>
            <h2 id="ask-olin-title" className={styles.modalTitle}>Ask Olin</h2>
            <p className={styles.modalSub}>Hermes Multi-Domain Orchestrator</p>
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          className={styles.closeButton}
          aria-label="Close Ask Olin"
        >
          <X size={16} weight="bold" />
        </button>
      </div>

      <div className={styles.chatStream} ref={chatStreamRef}>
        {messages.map((m) => (
          <div
            key={m.id}
            className={m.sender === 'user' ? styles.userMessage : styles.agentMessage}
          >
            {m.sender === 'agent' && (
              <div style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.65rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--olin-accent)', marginBottom: '6px', opacity: 0.9 }}>
                <Sparkle size={12} weight="fill" /> AI Synthesis
              </div>
            )}
            
            {m.text}

            {/* Personalization Explanation */}
            {m.hasPersonalization && (
              <div>
                <button
                  type="button"
                  onClick={() => toggleExplanation(m.id)}
                  className={styles.personalizationToggle}
                  aria-expanded={expandedExplanationId === m.id}
                >
                  <Brain size={14} weight="fill" />
                  Personalized using 2 memories + live data
                  {expandedExplanationId === m.id ? (
                    <CaretUp size={11} weight="bold" />
                  ) : (
                    <CaretDown size={11} weight="bold" />
                  )}
                </button>

                {expandedExplanationId === m.id && (
                  <div className={styles.personalizationBox}>
                    <div className={styles.boxHeader}>Used for this answer:</div>

                    {/* Section 1: Saved Context (Olin's Memory) */}
                    <div className={styles.contextSection}>
                      <span className={styles.sectionHeaderMemory}>
                        <Brain size={12} weight="fill" /> Saved Context (Olin&apos;s Memory)
                      </span>
                      <ul className={styles.contextList}>
                        <li>Prefers Mediterranean food (Active memory)</li>
                        <li>Avoids canned tuna · fresh tuna is fine (Active memory)</li>
                      </ul>
                    </div>

                    {/* Section 2: Current Live Data (Not Memory) */}
                    <div className={styles.contextSection}>
                      <span className={styles.sectionHeaderData}>
                        <Heartbeat size={12} weight="bold" /> Current Data (Domain Truth)
                      </span>
                      <ul className={styles.contextList}>
                        <li>Target: 2,000 kcal / 140g protein (from Nutrition service)</li>
                        <li>Household dinner time: ~19:00 (from Family routine)</li>
                      </ul>
                    </div>

                    <Link 
                      href="/memory" 
                      onClick={onClose} 
                      className={styles.manageMemoryLink}
                    >
                      Inspect Olin&apos;s Memory <ArrowRight size={11} weight="bold" />
                    </Link>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      <div className={styles.quickPrompts}>
        <button
          type="button"
          className={styles.promptBtn}
          onClick={() => handleSend('When does Ana arrive home?')}
        >
          Ana arrival time
        </button>
        <button
          type="button"
          className={styles.promptBtn}
          onClick={() => handleSend('Lock the front door')}
        >
          Lock front door
        </button>
        <button
          type="button"
          className={styles.promptBtn}
          onClick={() => handleSend('Log lunch bowl (420 kcal)')}
        >
          Log lunch (420 kcal)
        </button>
        <button
          type="button"
          className={styles.promptBtn}
          onClick={() => handleSend('Suggest dinner tonight')}
        >
          Suggest dinner
        </button>
      </div>

      <div className={styles.inputRow}>
        <input
          ref={inputRef}
          type="text"
          value={inputText}
          onChange={(e) => setCustomInput(e.target.value)}
          placeholder="Ask about schedule, family, home..."
          className={styles.queryInput}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              handleSend();
            }
          }}
        />
        <button
          type="button"
          onClick={() => handleSend()}
          className={styles.sendBtn}
          aria-label="Send query"
        >
          <ArrowUp size={16} weight="bold" />
        </button>
      </div>
    </div>
  );
}
