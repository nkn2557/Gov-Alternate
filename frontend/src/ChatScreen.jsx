import React, { useState, useEffect, useRef, useCallback } from 'react';

const ProgressStepper = ({ currentStep }) => {
    const steps = [
        { number: 1 },
        { number: 2 },
        { number: 3 },
        { number: 4 },
    ];

    const progressWidth = ((currentStep - 1) / (steps.length - 1)) * 100;

    return (
        <div className="container mb-4 mt-0">
            <div className="position-relative d-flex justify-content-between align-items-center" style={{ maxWidth: '800px', margin: '0 auto' }}>
                <div className="position-absolute w-100 bg-dark-subtle opacity-25" style={{ height: '4px', top: '50%', transform: 'translateY(-50%)', zIndex: 0 }}></div>
                <div
                    className="position-absolute bg-primary transition-width"
                    style={{
                        height: '4px',
                        top: '50%',
                        transform: 'translateY(-50%)',
                        zIndex: 0,
                        width: `${progressWidth}%`,
                        transition: 'width 0.5s ease-in-out'
                    }}
                ></div>
                {steps.map((step) => {
                    const isActive = step.number <= currentStep;
                    return (
                        <div key={step.number} className="d-flex flex-column align-items-center position-relative" style={{ zIndex: 1 }}>
                            <div
                                className={`d-flex justify-content-center align-items-center rounded-circle fw-bold shadow-sm transition-colors ${isActive ? 'bg-primary text-white' : 'bg-secondary-subtle text-muted'}`}
                                style={{ width: '40px', height: '40px', border: isActive ? 'none' : '1px solid #dee2e6' }}
                            >
                                {step.number}
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
};

const ChatScreen = ({
    municipality,
    form,
    setSearchResults,
    callAssistantAPI,
    downloadPDF
}) => {
    const [messages, setMessages] = useState([]);
    const [inputText, setInputText] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [expandedCardKeys, setExpandedCardKeys] = useState({});
    const messagesEndRef = useRef(null);
    const hasInitialized = useRef(false);
    const loadingMessageTimerRef = useRef(null);
    const [sessionId, setSessionId] = useState(null);

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    };

    useEffect(() => {
        const lastMsg = messages[messages.length - 1];
        if (lastMsg?.type === 'results') {
            // Scroll to the top of the results message so the user sees the start
            const elements = document.getElementsByClassName('chat-msg-entry');
            if (elements.length > 0) {
                elements[elements.length - 1].scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        } else {
            scrollToBottom();
        }
    }, [messages]);

    const addBotMessage = (text, type = 'text', payload = null, meta = {}) => {
        setMessages(prev => [...prev, { sender: 'bot', text, type, payload, ...meta }]);
    };

    const addUserMessage = (text) => {
        setMessages(prev => [...prev, { sender: 'user', text, type: 'text' }]);
    };

    const removeLoadingMessage = () => {
        setMessages(prev => prev.filter(msg => msg.type !== 'loading'));
    };

    const startLoadingIndicator = () => {
        if (loadingMessageTimerRef.current) {
            clearTimeout(loadingMessageTimerRef.current);
        }
        loadingMessageTimerRef.current = setTimeout(() => {
            addBotMessage("少々お待ちください...", "loading");
        }, 700);
    };

    const stopLoadingIndicator = () => {
        if (loadingMessageTimerRef.current) {
            clearTimeout(loadingMessageTimerRef.current);
            loadingMessageTimerRef.current = null;
        }
        removeLoadingMessage();
    };

    const toUiCards = (cards) => {
        if (!Array.isArray(cards)) return [];

        const toPreviewText = (value) => {
            const normalized = String(value || "").replace(/\s+/g, " ").trim();
            if (!normalized) return "";
            const maxChars = 120;
            if (normalized.length <= maxChars) return normalized;
            return `${normalized.slice(0, maxChars).trim()}...`;
        };

        return cards.map((card) => ({
            id: card.id || null,
            title: card.title || "タイトル不明",
            contentPreview: toPreviewText(card.content || ""),
            contentFull: card.content || "",
            steps: Array.isArray(card.steps) ? card.steps : [],
            urls: Array.isArray(card.official_urls) ? card.official_urls : [],
            displayNo: Number.isInteger(card.display_no) ? card.display_no : null,
        }));
    };

    const cardExpansionKey = (msgIndex, card, cardIndex) => {
        const idPart = card?.id || card?.title || `idx-${cardIndex}`;
        const noPart = Number.isInteger(card?.displayNo) ? card.displayNo : cardIndex;
        return `${msgIndex}:${noPart}:${idPart}`;
    };

    const toggleCardExpanded = (key) => {
        setExpandedCardKeys((prev) => ({
            ...prev,
            [key]: !prev[key],
        }));
    };

    const toSearchResultObject = (uiCards) => {
        return uiCards.reduce((acc, card, idx) => {
            acc[`domain${idx}`] = card;
            return acc;
        }, {});
    };

    const handleDownloadCardPdf = (msgIndex, cardIndex, card) => {
        if (typeof downloadPDF !== "function") return;
        const pdfKey = `chat-${msgIndex}-${card?.displayNo ?? (cardIndex + 1)}`;
        downloadPDF(pdfKey, {
            title: card?.title || "タイトル不明",
            content: card?.contentFull || card?.contentPreview || "",
            steps: Array.isArray(card?.steps) ? card.steps : [],
            urls: Array.isArray(card?.urls) ? card.urls : [],
        });
    };

    const buildInitialGuideMessage = useCallback(() => {
        const targetMunicipality = (municipality ?? "").trim();
        const opener = targetMunicipality
            ? `行政秘書です。自治体は「${targetMunicipality}」で承りました。次に、どのような制度や手続きをお探しか教えてください。`
            : "行政秘書です。初めに、お住まいの自治体名（例: 東京都千代田区）と、どのような制度や手続きをお探しかを教えてください。";

        return (
            `${opener}\n\n`
            + "次の情報があると、より精度高くご案内できます（入力できる範囲で構いません）。\n"
            + "1. 家族構成（夫婦[本人含む]・子ども・親[同居]の人数）\n"
            + "2. 各ご家族の年齢\n"
            + "3. 妊娠・出産予定\n"
            + "4. 今後の転居予定\n"
            + "5. 就労状況\n"
            + "6. 現在の世帯年収\n"
            + "7. ペットの有無"
        );
    }, [municipality]);

    const leadTextByAction = (nextAction, count = 0) => {
        switch (nextAction) {
            case "show_detail":
                return `${count}件の候補を表示しています。カードの「詳細を開く」から確認できます。`;
            case "show_more_options":
                return (
                    `${count}件の候補を表示しています。`
                    + "各カードの「詳細を開く」で説明と手順を確認できます。"
                    + "さらに見たい場合は下の「次の5件」ボタン、"
                    + "該当しない場合は「該当しない」、"
                    + "絞り込みたい場合は「条件: 小学生の子どもが2人」などと入力してください。"
                );
            case "present_list":
                return (
                    `${count}件の候補を表示しています。`
                    + "各カードの「詳細を開く」で説明と手順を確認できます。"
                    + "もっと見たい場合は下の「次の5件」ボタン、"
                    + "該当しない場合は「該当しない」、"
                    + "条件を絞る場合は「条件: 小学生の子どもが2人」などと入力してください。"
                );
            default:
                return `${count}件の候補を表示しています。`;
        }
    };

    const askAssistant = async (
        userMessage = null,
        domainOverride = null,
        municipalityOverride = null,
        requestMore = false,
    ) => {
        const targetMunicipality = (municipalityOverride ?? municipality ?? "").trim();
        const targetDomain = (domainOverride ?? form?.domain ?? "").trim();

        setIsLoading(true);
        startLoadingIndicator();

        try {
            const result = await callAssistantAPI({
                municipality: targetMunicipality || undefined,
                domain: targetDomain || undefined,
                profile: form || {},
                user_message: userMessage || undefined,
                session_id: sessionId || undefined,
                expect_tool_result: false,
                request_more: requestMore,
            });

            stopLoadingIndicator();

            if (result.session_id) {
                setSessionId(result.session_id);
            }

            const uiCards = toUiCards(result.cards);
            const hasCards = uiCards.length > 0;
            if (result.assistant_text && result.assistant_text.trim()) {
                const shouldShowAssistantText = !hasCards;
                if (shouldShowAssistantText) {
                    addBotMessage(result.assistant_text.trim());
                }
            }

            if (uiCards.length > 0) {
                setSearchResults(toSearchResultObject(uiCards));
                addBotMessage(
                    leadTextByAction(result.next_action, uiCards.length),
                    "results",
                    uiCards,
                    {
                        allowNextFive: result.next_action === "present_list" || result.next_action === "show_more_options",
                    }
                );
            }
        } catch (error) {
            console.error("Error calling assistant API:", error);
            stopLoadingIndicator();
            const detail = error?.message ? `\n(${error.message})` : "";
            addBotMessage(
                `接続に失敗しました。バックエンドが起動しているか、API URL / CORS 設定を確認してください。${detail}`
            );
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => {
        if (hasInitialized.current) return;
        hasInitialized.current = true;
        addBotMessage(buildInitialGuideMessage());
    }, [buildInitialGuideMessage]);

    useEffect(() => {
        return () => {
            if (loadingMessageTimerRef.current) {
                clearTimeout(loadingMessageTimerRef.current);
            }
        };
    }, []);

    const handleSend = async () => {
        if (!inputText.trim()) return;

        const text = inputText;
        setInputText('');
        addUserMessage(text);
        await askAssistant(text);
    };

    const handleNextFive = async () => {
        if (isLoading) return;
        const nextFiveMessage = "次の5件";
        addUserMessage(nextFiveMessage);
        await askAssistant(nextFiveMessage, null, null, true);
    };

    const handleKeyDown = (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            if (e.nativeEvent.isComposing) return;
            e.preventDefault();
            handleSend();
        }
    };

    return (
        <div className="d-flex flex-column h-100 chat-container">
            {/* Chat Area */}
            <div className="flex-grow-1 overflow-auto p-3" style={{ backgroundColor: '#f5f7f9' }}>
                {messages.map((msg, index) => (
                    <div key={index} className={`d-flex mb-3 chat-msg-entry ${msg.sender === 'user' ? 'justify-content-end' : 'justify-content-start'}`}>
                        <div className={`p-3 rounded-3 shadow-sm ${msg.sender === 'user' ? 'bg-primary text-white' : 'bg-white'}`} style={{ maxWidth: msg.type === 'results' ? '95%' : '80%' }}>

                            {/* Text Message */}
                            {msg.type === 'text' && (
                                <div style={{ whiteSpace: 'pre-wrap', textAlign: 'left' }}>
                                    {msg.text}
                                </div>
                            )}

                            {/* Results Display (InfoScreen Style) */}
                            {msg.type === 'results' && (
                                <div>
                                    <div className="mb-3">{msg.text}</div>
                                    {msg.payload.map((result, i) => {
                                        const expansionKey = cardExpansionKey(index, result, i);
                                        const isExpanded = !!expandedCardKeys[expansionKey];
                                        const hasExpandableBody = Boolean(
                                            (typeof result.contentFull === 'string' && result.contentFull.trim())
                                            || (Array.isArray(result.steps) && result.steps.length > 0)
                                        );
                                        return (
                                        <div key={expansionKey} className="card shadow-sm border-0 mb-4">
                                            <div className="card-body text-start p-3">
                                                <div className="d-flex align-items-center justify-content-start gap-2 mb-2">
                                                    <span className="badge bg-secondary">
                                                        候補 {result.displayNo ?? (i + 1)}
                                                    </span>
                                                    <h4 className="card-title text-primary fw-bold mb-0">{result.title}</h4>
                                                </div>
                                                {result.contentPreview && !isExpanded && (
                                                    <p
                                                        className="card-text mb-3 small"
                                                        style={{
                                                            lineHeight: '1.5',
                                                        }}
                                                    >
                                                        {result.contentPreview}
                                                    </p>
                                                )}

                                                {hasExpandableBody && (
                                                    <button
                                                        type="button"
                                                        className="btn btn-outline-primary btn-sm mb-3"
                                                        onClick={() => toggleCardExpanded(expansionKey)}
                                                    >
                                                        {isExpanded ? "詳細を閉じる" : "詳細を開く"}
                                                    </button>
                                                )}

                                                {isExpanded && result.contentFull && (
                                                    <div className="mb-3">
                                                        <h6 className="fw-bold mb-2 text-secondary">制度の説明</h6>
                                                        <p className="card-text small mb-0" style={{ whiteSpace: 'pre-wrap' }}>
                                                            {result.contentFull}
                                                        </p>
                                                    </div>
                                                )}

                                                {isExpanded && result.steps && result.steps.length > 0 && (
                                                    <div className="bg-light p-2 rounded-3 text-start">
                                                        <h6 className="fw-bold mb-2 text-secondary">手続きの流れ</h6>
                                                        <ul className="list-group list-group-flush bg-transparent">
                                                            {result.steps.map((step, idx) => (
                                                                <li key={idx} className="list-group-item px-0 bg-transparent border-bottom-0 pb-1 small">
                                                                    <span className="badge bg-primary rounded-pill me-2">{idx + 1}</span>
                                                                    {step}
                                                                </li>
                                                            ))}
                                                        </ul>
                                                    </div>
                                                )}

                                                {isExpanded && result.urls && result.urls.length > 0 && (
                                                    <div className="mt-3">
                                                        <p className="small text-muted mb-2">参照元</p>
                                                        <div className="d-flex justify-content-start gap-2 flex-wrap">
                                                            {result.urls.map((url, idx) => (
                                                                <a
                                                                    key={idx}
                                                                    href={url}
                                                                    target="_blank"
                                                                    rel="noopener noreferrer"
                                                                    className="btn btn-white rounded-circle shadow-sm border d-flex align-items-center justify-content-center hover-card"
                                                                    style={{ width: '40px', height: '40px' }}
                                                                    title={url}
                                                                >
                                                                    <img
                                                                        src={`https://www.google.com/s2/favicons?domain=${new URL(url).hostname}&sz=64`}
                                                                        alt="URL"
                                                                        width="20"
                                                                        height="20"
                                                                    />
                                                                </a>
                                                            ))}
                                                        </div>
                                                    </div>
                                                )}

                                                {typeof downloadPDF === "function" && (
                                                    <div className="mt-3">
                                                        <button
                                                            type="button"
                                                            className="btn btn-outline-primary btn-sm"
                                                            onClick={() => handleDownloadCardPdf(index, i, result)}
                                                        >
                                                            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" fill="currentColor" className="bi bi-download me-2" viewBox="0 0 16 16">
                                                                <path d="M.5 9.9a.5.5 0 0 1 .5.5v2.5a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-2.5a.5.5 0 0 1 1 0v2.5a2 2 0 0 1-2 2H2a2 2 0 0 1-2-2v-2.5a.5.5 0 0 1 .5-.5" />
                                                                <path d="M7.646 11.854a.5.5 0 0 0 .708 0l3-3a.5.5 0 0 0-.708-.708L8.5 10.293V1.5a.5.5 0 0 0-1 0v8.793L5.354 8.146a.5.5 0 1 0-.708.708l3 3z" />
                                                            </svg>
                                                            PDFダウンロード
                                                        </button>
                                                    </div>
                                                )}
                                            </div>
                                        </div>
                                    )})}
                                    {msg.allowNextFive && (
                                        <div className="d-flex justify-content-center">
                                            <button
                                                type="button"
                                                className="btn btn-outline-secondary btn-sm"
                                                onClick={handleNextFive}
                                                disabled={isLoading}
                                            >
                                                次の5件
                                            </button>
                                        </div>
                                    )}
                                </div>
                            )}

                            {/* Loading */}
                            {msg.type === 'loading' && (
                                <div className="d-flex align-items-center">
                                    <div className="spinner-border spinner-border-sm me-2" role="status"></div>
                                    {msg.text}
                                </div>
                            )}
                        </div>
                    </div>
                ))}
                <div ref={messagesEndRef} />
            </div>

            {/* Input Area */}
            <div className="p-3 bg-white border-top">
                <div className="input-group">
                    <input
                        type="text"
                        className="form-control"
                        placeholder="メッセージを入力..."
                        value={inputText}
                        onChange={(e) => setInputText(e.target.value)}
                        onKeyDown={handleKeyDown}
                        disabled={isLoading}
                    />
                    <button className="btn btn-primary" onClick={handleSend} disabled={isLoading || !inputText.trim()}>
                        送信
                    </button>
                </div>
            </div>
        </div>
    );
};

export default ChatScreen;
