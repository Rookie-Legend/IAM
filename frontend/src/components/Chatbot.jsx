import React, { useState, useRef } from 'react';
import { apiUrl } from '../stores/configStore';

const Chatbot = ({ token, user }) => {
    const [isOpen, setIsOpen] = useState(false);
    const [messages, setMessages] = useState([{ role: 'bot', text: 'How can I help you with IAM decisions today?' }]);
    const [input, setInput] = useState('');
    const inputRef = useRef(null);

    const handleSend = async () => {
        if (!input.trim()) return;
        const userMsg = { role: 'user', text: input };
        setMessages([...messages, userMsg]);
        setInput('');

        const response = await fetch(apiUrl('/api/orchestrator/request-access'), {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({ user_id: user?.user_id || user?._id, resource_id: input })
        });
        const data = await response.json();
        
        setMessages(prev => [...prev, { role: 'bot', text: data.message }]);
        setTimeout(() => inputRef.current?.focus(), 10);
    };

    return (
        <div style={{ position: 'fixed', bottom: '2rem', right: '2rem', zIndex: 1000 }}>
            {isOpen ? (
                <div className="glass" style={{ width: '350px', height: '500px', display: 'flex', flexDirection: 'column', padding: '1rem', border: '1px solid var(--primary)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '1rem' }}>
                        <h3 style={{ margin: 0 }}>IAM Assistant</h3>
                        <button className="btn" onClick={() => setIsOpen(false)}>×</button>
                    </div>
                    <div style={{ flex: 1, overflowY: 'auto', marginBottom: '1rem', paddingRight: '5px' }}>
                        {messages.map((m, i) => (
                            <div key={i} style={{ 
                                alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start',
                                background: m.role === 'user' ? 'var(--primary)' : 'rgba(255,255,255,0.1)',
                                padding: '8px 12px',
                                borderRadius: '12px',
                                marginBottom: '10px',
                                maxWidth: '80%',
                                marginLeft: m.role === 'user' ? 'auto' : '0'
                            }}>
                                {m.text}
                            </div>
                        ))}
                    </div>
                    <div style={{ display: 'flex', gap: '5px' }}>
                        <input 
                            ref={inputRef} 
                            autoFocus 
                            value={input} 
                            onChange={(e) => setInput(e.target.value)} 
                            onKeyPress={(e) => e.key === 'Enter' && handleSend()} 
                            placeholder="Ask something..." 
                            onClick={(e) => e.stopPropagation()} 
                            style={{ flex: 1, padding: '10px 15px', borderRadius: '8px', border: '2px solid var(--primary)', outline: 'none', background: 'rgba(0,0,0,0.2)', color: 'white' }} 
                            className="focus:shadow-[0_0_15px_rgba(0,255,170,0.3)] transition-all duration-200" 
                        />
                        <button className="btn btn-primary" onClick={handleSend}>Send</button>
                    </div>
                </div>
            ) : (
                <button className="btn btn-primary" style={{ borderRadius: '50%', width: '60px', height: '60px', fontSize: '24px' }} onClick={() => setIsOpen(true)}>
                    💬
                </button>
            )}
        </div>
    );
};

export default Chatbot;
