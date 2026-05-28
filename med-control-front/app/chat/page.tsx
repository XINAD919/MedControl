'use client'

import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useSession } from 'next-auth/react'
import { connectChatSocket, fetchDocument, uploadDocument } from '../lib/api'
import type { ChatMessage, UploadStatus } from '../lib/types'
import { Send, Bot, User, AlertCircle, Trash2, Paperclip, X } from 'lucide-react'

function UserBubble({ content }: { content: string }) {
  return (
    <div className="flex items-end gap-2 justify-end">
      <div className="max-w-[75%] bg-blue-500 text-white rounded-2xl rounded-br-sm px-4 py-3 text-sm leading-relaxed">
        {content}
      </div>
      <div className="shrink-0 size-7 bg-blue-100 rounded-full flex items-center justify-center mb-0.5">
        <User size={14} className="text-blue-500" />
      </div>
    </div>
  )
}

function AssistantBubble({ content, streaming }: { content: string; streaming?: boolean }) {
  return (
    <div className="flex items-end gap-2">
      <div className="shrink-0 size-7 bg-blue-500 rounded-full flex items-center justify-center mb-0.5">
        <Bot size={14} className="text-white" />
      </div>
      <div className="max-w-[90%] sm:max-w-[75%] bg-white text-gray-800 rounded-2xl rounded-bl-sm px-4 py-3 text-sm shadow-sm border border-blue-50 leading-relaxed">
        {content ? (
          <div className="md-prose"><ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown></div>
        ) : streaming ? (
          <span className="flex gap-1 items-center h-4">
            <span className="size-1.5 bg-gray-300 rounded-full animate-pulse [animation-delay:0ms]" />
            <span className="size-1.5 bg-gray-300 rounded-full animate-pulse [animation-delay:300ms]" />
            <span className="size-1.5 bg-gray-300 rounded-full animate-pulse [animation-delay:600ms]" />
          </span>
        ) : null}
      </div>
    </div>
  )
}

const STORAGE_KEY = 'medcontrol_chat_messages'

function loadMessages(): ChatMessage[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as ChatMessage[]) : []
  } catch {
    return []
  }
}

export default function ChatPage() {
  const { data: session, status } = useSession()
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [streamingContent, setStreamingContent] = useState('')
  const [streamError, setStreamError] = useState(false)
  const [uploadStatus, setUploadStatus] = useState<UploadStatus>('idle')
  const [uploadedFile, setUploadedFile] = useState<File | null>(null)
  const [pendingDocId, setPendingDocId] = useState<string | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const pollingTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Cargar historial desde localStorage al montar
  useEffect(() => {
    const loaded = loadMessages()
    if (loaded.length > 0) {
      Promise.resolve().then(() => {
        setMessages(loaded)
      })
    }
  }, [])

  // Persistir mensajes cuando cambian
  useEffect(() => {
    if (messages.length > 0) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(messages))
    }
  }, [messages])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamingContent])

  useEffect(() => {
    if (uploadStatus !== 'processing' || !pendingDocId || !session) return

    let cancelled = false
    let attempts = 0
    const MAX_ATTEMPTS = 30

    const poll = async () => {
      if (cancelled) return
      try {
        const doc = await fetchDocument(session, pendingDocId)
        if (doc.processed) {
          if (!cancelled) setUploadStatus('ready')
          return
        }
      } catch { /* transient error — keep polling */ }
      attempts++
      if (attempts >= MAX_ATTEMPTS) {
        if (!cancelled) setUploadStatus('error')
        return
      }
      pollingTimeoutRef.current = setTimeout(poll, 2000)
    }

    pollingTimeoutRef.current = setTimeout(poll, 2000)
    return () => {
      cancelled = true
      if (pollingTimeoutRef.current) clearTimeout(pollingTimeoutRef.current)
    }
  }, [uploadStatus, pendingDocId, session])

  if (status === 'loading') {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="size-6 border-2 border-blue-300 border-t-blue-500 rounded-full animate-spin" />
      </div>
    )
  }
  if (!session) return null

  const handleFileSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    // Reset so the same file can be re-selected after dismissal
    e.target.value = ''

    setUploadedFile(file)
    setUploadStatus('uploading')

    try {
      const doc = await uploadDocument(session, file)
      setPendingDocId(doc.id)
      setUploadStatus('processing')
      setInput('He subido una receta médica. Por favor analízala y configura los recordatorios.')
      textareaRef.current?.focus()
    } catch {
      setUploadStatus('error')
    }
  }

  const handleSubmit = () => {
    const text = input.trim()
    if (!text || isStreaming || uploadStatus === 'processing') return

    setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'user', content: text }])
    setInput('')
    setUploadStatus('idle')
    setUploadedFile(null)
    if (pollingTimeoutRef.current) clearTimeout(pollingTimeoutRef.current)
    setPendingDocId(null)
    setIsStreaming(true)
    setStreamingContent('')
    setStreamError(false)

    // capture content across closures
    let accumulated = ''

    connectChatSocket(
      session,
      text,
      (token) => {
        accumulated += token
        setStreamingContent(accumulated)
      },
      () => {
        if (accumulated) {
          setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'assistant', content: accumulated }])
        }
        setStreamingContent('')
        setIsStreaming(false)
        textareaRef.current?.focus()
      },
      () => {
        setStreamError(true)
        setStreamingContent('')
        setIsStreaming(false)
      },
    )
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const isEmpty = messages.length === 0 && !isStreaming

  return (
    <div className="h-full max-h-screen flex flex-col">
      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*,.pdf"
        aria-label="Subir receta médica"
        className="hidden"
        onChange={handleFileSelected}
      />
      {/* Header */}
      <div className="bg-white border-b border-blue-50 px-5 py-4 pl-16 sm:pl-5 flex items-center gap-3 shrink-0">
        <div className="size-8 bg-blue-500 rounded-full flex items-center justify-center">
          <Bot size={16} className="text-white" />
        </div>
        <div>
          <h1 className="text-sm font-semibold text-gray-800">MedControl AI</h1>
          <p className="text-xs text-gray-400">Asistente de adherencia médica</p>
        </div>
        <div className="ml-auto flex items-center gap-3">
          {messages.length > 0 && !isStreaming && (
            <button
              type="button"
              onClick={() => { setMessages([]); localStorage.removeItem(STORAGE_KEY) }}
              title="Limpiar conversación"
              className="text-gray-300 hover:text-red-400 transition-colors"
            >
              <Trash2 size={15} />
            </button>
          )}
          <div className={`size-2 rounded-full ${isStreaming ? 'bg-blue-400 animate-pulse' : 'bg-green-400'}`} />
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-5 flex flex-col gap-4">
        {isEmpty && (
          <div className="flex flex-col items-center justify-center h-full gap-3 text-center">
            <div className="size-14 bg-blue-50 rounded-2xl flex items-center justify-center">
              <Bot size={28} className="text-blue-400" />
            </div>
            <div>
              <p className="text-sm font-semibold text-gray-700">Hola, soy MedControl</p>
              <p className="text-xs text-gray-400 mt-1 max-w-xs">
                Puedo ayudarte a programar recordatorios de medicamentos, consultar tu agenda y más.
              </p>
            </div>
            <div className="flex flex-col gap-2 mt-2">
              {['¿Qué recordatorios tengo hoy?', 'Crear recordatorio para Losartán a las 8am', '¿Cuándo es mi próxima dosis?'].map(suggestion => (
                <button
                  key={suggestion}
                  onClick={() => { setInput(suggestion); textareaRef.current?.focus() }}
                  className="text-xs text-blue-500 border border-blue-100 bg-white hover:bg-blue-50 rounded-full px-4 py-1.5 transition-colors"
                type="button"
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) =>
          msg.role === 'user'
            ? <UserBubble key={msg.id ?? i} content={msg.content} />
            : <AssistantBubble key={msg.id ?? i} content={msg.content} />
        )}

        {/* In-progress streaming bubble */}
        {isStreaming && (
          <AssistantBubble content={streamingContent} streaming />
        )}

        {streamError && (
          <div className="flex items-center gap-2 text-xs text-red-400 bg-red-50 rounded-xl px-4 py-3 border border-red-100">
            <AlertCircle size={14} />
            <span>Error de conexión. Intenta de nuevo.</span>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Upload preview panel */}
      {uploadStatus !== 'idle' && uploadedFile && (
        <div className="bg-blue-50 border-t border-blue-100 px-4 py-2 flex items-center gap-3 shrink-0">
          <Paperclip size={13} className="text-blue-300 shrink-0" />
          <div className="flex-1 min-w-0">
            <span className="text-xs font-medium text-gray-600 truncate block">{uploadedFile.name}</span>
            {uploadStatus === 'uploading' && (
              <span className="text-xs text-blue-400">Subiendo…</span>
            )}
            {uploadStatus === 'processing' && (
              <span className="text-xs text-blue-400 flex items-center gap-1">
                <span className="size-3 border border-blue-300 border-t-blue-500 rounded-full animate-spin inline-block" />
                Analizando prescripción…
              </span>
            )}
            {uploadStatus === 'ready' && (
              <span className="text-xs text-green-500">Listo — puedes enviar el mensaje</span>
            )}
            {uploadStatus === 'error' && (
              <span className="text-xs text-red-400">Error al procesar. Intenta de nuevo.</span>
            )}
          </div>
          <button
            type="button"
            onClick={() => {
              if (pollingTimeoutRef.current) clearTimeout(pollingTimeoutRef.current)
              setPendingDocId(null)
              setUploadStatus('idle')
              setUploadedFile(null)
            }}
            className="text-gray-300 hover:text-gray-500 shrink-0"
          >
            <X size={13} />
          </button>
        </div>
      )}

      {/* Input bar */}
      <div className="bg-white border-t border-blue-50 px-4 py-3 shrink-0">
        <div className="flex items-end gap-2 bg-gray-50 rounded-2xl px-4 py-2.5 border border-gray-100 focus-within:border-blue-200 focus-within:ring-2 focus-within:ring-blue-100 transition-all">
          {/* Paperclip — upload prescription */}
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={isStreaming || uploadStatus === 'uploading' || uploadStatus === 'processing'}
            title="Subir receta médica"
            className="shrink-0 size-7 text-gray-300 hover:text-blue-400 flex items-center justify-center disabled:opacity-40 disabled:cursor-not-allowed transition-colors mb-0.5"
          >
            <Paperclip size={15} />
          </button>
          <textarea
            ref={textareaRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isStreaming}
            aria-label="Escribe un mensaje"
            placeholder="Escribe un mensaje… (Enter para enviar, Shift+Enter para nueva línea)"
            rows={1}
            className="flex-1 bg-transparent text-sm text-gray-700 placeholder-gray-300 resize-none focus:outline-none max-h-32 leading-relaxed disabled:opacity-50"
            style={{ fieldSizing: 'content' } as React.CSSProperties}
          />
          <button
            type="button"
            onClick={handleSubmit}
            disabled={!input.trim() || isStreaming || uploadStatus === 'processing'}
            className="shrink-0 size-8 bg-blue-500 text-white rounded-xl flex items-center justify-center hover:bg-blue-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors mb-0.5"
          >
            <Send size={14} />
          </button>
        </div>
        <p className="text-xs text-gray-300 text-center mt-1.5">Enter para enviar, Shift+Enter para nueva línea</p>
      </div>
    </div>
  )
}
