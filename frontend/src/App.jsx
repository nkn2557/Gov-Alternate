import React, { useState, useEffect } from 'react';
import ChatScreen from './ChatScreen';
import 'bootstrap/dist/css/bootstrap.min.css';
import './App.css';
import logo from './assets/4.svg'; // Import the logo
import jsPDF from 'jspdf';
import 'jspdf-autotable';
import NotoSansJP from './NotoSansJP-Regular-base64.js';
if (typeof jsPDF !== 'undefined') {
  jsPDF.API.events.push(['addFonts', function() {
    this.addFileToVFS('NotoSansJP-Regular.ttf', NotoSansJP);
    this.addFont('NotoSansJP-Regular.ttf', 'NotoSansJP', 'normal');
    this.addFont('NotoSansJP-Regular.ttf', 'NotoSansJP', 'bold');
  }]);
}

// --- Mock Data ---
const categories = [
  {
    id: 'moving',
    title: '引越し',
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" fill="currentColor" className="bi bi-house-door" viewBox="0 0 16 16">
        <path d="M8.354 1.146a.5.5 0 0 0-.708 0l-6 6A.5.5 0 0 0 1.5 7.5v7a.5.5 0 0 0 .5.5h4.5a.5.5 0 0 0 .5-.5v-4h2v4a.5.5 0 0 0 .5.5H14a.5.5 0 0 0 .5-.5v-7a.5.5 0 0 0-.146-.354L13 5.793V2.5a.5.5 0 0 0-.5-.5h-1a.5.5 0 0 0-.5.5v1.293L8.354 1.146zM2.5 14V7.707l5.5-5.5 5.5 5.5V14H10v-4a.5.5 0 0 0-.5-.5h-3a.5.5 0 0 0-.5.5v4H2.5z" />
      </svg>
    )
  },
  // { 
  //   id: 'marriage', 
  //   title: '結婚', 
  //   icon: (
  //     <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" fill="currentColor" className="bi bi-heart" viewBox="0 0 16 16">
  //       <path d="m8 2.748-.717-.737C5.6.281 2.514.878 1.4 3.053c-.523 1.023-.641 2.5.314 4.385.92 1.815 2.834 3.989 6.286 6.357 3.452-2.368 5.365-4.542 6.286-6.357.955-1.886.838-3.362.314-4.385C13.486.878 10.4.281 8.717 2.01L8 2.748zM8 15C-7.333 4.868 3.279-3.04 7.824 1.143c.06.055.119.112.176.171a3.12 3.12 0 0 1 .176-.17C12.72-3.042 23.333 4.867 8 15z"/>
  //     </svg>
  //   )
  // },
  {
    id: 'childcare',
    title: '子育て',
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" fill="currentColor" className="bi bi-person-plus" viewBox="0 0 16 16">
        <path d="M6 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6zm2-3a2 2 0 1 1-4 0 2 2 0 0 1 4 0zm4 8c0 1-1 1-1 1H1s-1 0-1-1 1-4 6-4 6 3 6 4zm-1-.004c-.001-.246-.154-.986-.832-1.664C9.516 10.68 8.289 10 6 10c-2.29 0-3.516.68-4.168 1.332-.678.678-.83 1.418-.832 1.664h10z" />
        <path fillRule="evenodd" d="M13.5 5a.5.5 0 0 1 .5.5V7h1.5a.5.5 0 0 1 0 1H14v1.5a.5.5 0 0 1-1 0V8h-1.5a.5.5 0 0 1 0-1H13V5.5a.5.5 0 0 1 .5-.5z" />
      </svg>
    )
  },
  // { 
  //   id: 'tax', 
  //   title: '税金', 
  //   icon: (
  //     <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" fill="currentColor" className="bi bi-cash" viewBox="0 0 16 16">
  //       <path d="M8 10a2 2 0 1 0 0-4 2 2 0 0 0 0 4"/>
  //       <path d="M0 4a1 1 0 0 1 1-1h14a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H1a1 1 0 0 1-1-1zm3 0a2 2 0 0 1-2 2v4a2 2 0 0 1 2 2h10a2 2 0 0 1 2-2V6a2 2 0 0 1-2-2z"/>
  //     </svg>
  //   )
  // },
  {
    id: 'explorer',
    title: '全カテゴリ',
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" fill="currentColor" className="bi bi-magic" viewBox="0 0 16 16">
        <path d="M9.5 2.672a.5.5 0 1 0 1 0V.843a.5.5 0 0 0-1 0zm4.5.035A.5.5 0 0 0 13.293 2L12 3.293a.5.5 0 1 0 .707.707zM7.293 4A.5.5 0 1 0 8 3.293L6.707 2A.5.5 0 0 0 6 2.707zm-.621 2.5a.5.5 0 1 0 0-1H4.843a.5.5 0 1 0 0 1zm8.485 0a.5.5 0 1 0 0-1h-1.829a.5.5 0 0 0 0 1zM13.293 10A.5.5 0 1 0 14 9.293L12.707 8a.5.5 0 1 0-.707.707zM9.5 11.157a.5.5 0 0 0 1 0V9.328a.5.5 0 0 0-1 0zm1.854-5.097a.5.5 0 0 0 0-.706l-.708-.708a.5.5 0 0 0-.707 0L8.646 5.94a.5.5 0 0 0 0 .707l.708.708a.5.5 0 0 0 .707 0l1.293-1.293Zm-3 3a.5.5 0 0 0 0-.706l-.708-.708a.5.5 0 0 0-.707 0L.646 13.94a.5.5 0 0 0 0 .707l.708.708a.5.5 0 0 0 .707 0z" />
      </svg>
    )
  },
];

const catchCopies = {
  first: '情報を一元化',
  second: 'あなたのための情報を提供',
  third: 'チェックリストを自動作成',
};

const subCopies = {
  first: 'それぞれの行政サイトに分散した情報をまとめて提供',
  second: '近い将来必要となる手続きを予測してお知らせ',
  third: '何をすればいいかを分かりやすくガイド',
};

const infoData = {
  moving: {
    title: '転出届・転入届について',
    content: '引越しをする際は、旧住所の役所で転出届を、新住所の役所で転入届を提出する必要があります。マイナンバーカードをお持ちの方はオンラインでの手続きも可能です。',
    steps: ['転出届の提出（旧住所）', '転入届の提出（新住所）', 'マイナンバーカードの住所変更'],
    urls: ['https://www.city.chiyoda.lg.jp/koho/kurashi/koseki/jumintoroku/tenshutsu.html', 'https://www.city.chiyoda.lg.jp/koho/kurashi/koseki/jumintoroku/tennyu.html']
  },
  birth: {
    title: '出生届・児童手当について',
    content: '赤ちゃんが生まれたら、生まれた日を含めて14日以内に出生届を提出する必要があります。あわせて児童手当や乳幼児医療費助成の手続きも行いましょう。',
    steps: ['出生届の提出（14日以内）', '児童手当の認定請求', '健康保険への加入手続き', '乳幼児医療費助成の申請'],
    urls: ['https://www.city.chiyoda.lg.jp/koho/kurashi/koseki/koseki/todokede.html', 'https://www.city.chiyoda.lg.jp/kosodate/teate/shussanhiyojosei.html']
  },
};

const featureIcons = {
  first: (
    <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" fill="currentColor" className="bi bi-collection" viewBox="0 0 16 16">
      <path d="M2.5 3.5a.5.5 0 0 1 0-1h11a.5.5 0 0 1 0 1h-11zm2-2a.5.5 0 0 1 0-1h7a.5.5 0 0 1 0 1h-7zM0 13a1.5 1.5 0 0 0 1.5 1.5h13A1.5 1.5 0 0 0 16 13V6a1.5 1.5 0 0 0-1.5-1.5h-13A1.5 1.5 0 0 0 0 6v7zm1.5.5A.5.5 0 0 1 1 13V6a.5.5 0 0 1 .5-.5h13a.5.5 0 0 1 .5.5v7a.5.5 0 0 1-.5.5h-13z" />
    </svg>
  ),
  second: (
    <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" fill="currentColor" className="bi bi-signpost-split" viewBox="0 0 16 16">
      <path d="M7 7V1.414a1 1 0 0 1 2 0V2h5a1 1 0 0 1 .8.4l.975 1.3a.5.5 0 0 1 0 .6L14.8 5.6a1 1 0 0 1-.8.4H9v10H7v-5H2a1 1 0 0 1-.8-.4L.225 9.3a.5.5 0 0 1 0-.6L1.2 7.4A1 1 0 0 1 2 7zm1 3V8H2l-.75 1L2 10zm0-5h6l.75-1L14 3H8z" />
    </svg>
  ),
  third: (
    <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" fill="currentColor" className="bi bi-list-check" viewBox="0 0 16 16">
      <path d="M5 11.5a.5.5 0 0 1 .5-.5h9a.5.5 0 0 1 0 1h-9a.5.5 0 0 1-.5-.5m0-4a.5.5 0 0 1 .5-.5h9a.5.5 0 0 1 0 1h-9a.5.5 0 0 1-.5-.5m0-4a.5.5 0 0 1 .5-.5h9a.5.5 0 0 1 0 1h-9a.5.5 0 0 1-.5-.5M3.854 2.146a.5.5 0 0 1 0 .708l-1.5 1.5a.5.5 0 0 1-.708 0l-.5-.5a.5.5 0 1 1 .708-.708L2 3.293l1.146-1.147a.5.5 0 0 1 .708 0m0 4a.5.5 0 0 1 0 .708l-1.5 1.5a.5.5 0 0 1-.708 0l-.5-.5a.5.5 0 1 1 .708-.708L2 7.293l1.146-1.147a.5.5 0 0 1 .708 0m0 4a.5.5 0 0 1 0 .708l-1.5 1.5a.5.5 0 0 1-.708 0l-.5-.5a.5.5 0 0 1 .708-.708l.146.147 1.146-1.147a.5.5 0 0 1 .708 0" />
    </svg>
  )
};

const supportIcons = {
  search: (
    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" className="bi bi-search" viewBox="0 0 16 16">
      <path d="M11.742 10.344a6.5 6.5 0 1 0-1.397 1.398h-.001q.044.06.098.115l3.85 3.85a1 1 0 0 0 1.415-1.414l-3.85-3.85a1 1 0 0 0-.115-.1zM12 6.5a5.5 5.5 0 1 1-11 0 5.5 5.5 0 0 1 11 0" />
    </svg>
  )
}

// --- Functions ---
const API_TEST_URL = "https://cloudrun-test-1064051725530.asia-northeast1.run.app";
const ASSISTANT_API_BASE_URL =
  import.meta.env.VITE_ASSISTANT_API_BASE_URL ||
  import.meta.env.VITE_API_BASE_URL ||
  // "http://localhost:8000" ||
  "https://cr-gov-sec-1064051725530.asia-northeast1.run.app";

function callTestAPI() {
  fetch(`${API_TEST_URL}`)
    .then(response => response.json())
    .then(data => {
      console.log("API Response:", data);
      alert(`API Response: ${JSON.stringify(data)}`);
    })
    .catch(error => {
      console.error("Error calling API:", error);
      alert(`Error calling API: ${error}`);
    });
}

async function callSearchAPI(payload) {
  try {
    const response = await fetch(`${ASSISTANT_API_BASE_URL}/v1/search-fs/search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        municipality: payload.municipality,
        domain: payload.domain,
        chat_context: {
          inputs: payload.inputs
        }
      })
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(`HTTP error! status: ${response.status}, detail: ${errorData?.detail || 'Unknown error'}`);
    }

    const resData = await response.json();
    console.log("Search API response:", resData);
    
    return {
      success: true,
      data: resData
    };
  } catch (error) {
    console.error("Search API error:", error);
    return {
      success: false,
      error: error.message,
      message: error.message
    };
  }
}

async function callAssistantAPI(payload) {
  try {
    const response = await fetch(`${ASSISTANT_API_BASE_URL}/v1/assistant/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      const detail = errorData?.detail ? `: ${errorData.detail}` : "";
      throw new Error(`HTTP error! status: ${response.status}${detail}`);
    }

    return await response.json();
  } catch (error) {
    console.error("Assistant API error:", error);
    throw error;
  }
}

const loadImageAsBase64 = async (url) => {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = 'Anonymous';
    img.onload = () => {
      const canvas = document.createElement('canvas');
      canvas.width = img.width;
      canvas.height = img.height;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(img, 0, 0);
      resolve(canvas.toDataURL('image/png'));
    };
    img.onerror = reject;
    img.src = url;
  });
};

// 日本語フォント対応版 - リッチデザイン
const downloadPDF = async (key, data) => {
  try {
    const pdf = new jsPDF({
      orientation: 'portrait',
      unit: 'mm',
      format: 'a4'
    });

    // フォントを登録
    try {
      pdf.addFileToVFS('NotoSansJP-Regular.ttf', NotoSansJP);
      pdf.addFont('NotoSansJP-Regular.ttf', 'NotoSansJP', 'normal');
    } catch (e) {
      // 既に登録済みの場合はエラーを無視
    }

    const pageWidth = pdf.internal.pageSize.getWidth();
    const pageHeight = pdf.internal.pageSize.getHeight();
    const margin = 15;
    const contentWidth = pageWidth - (margin * 2);
    let yPos = 20;

    // ヘッダー背景（プライマリカラー）
    pdf.setFillColor(13, 110, 253); // Bootstrap primary blue
    pdf.rect(0, 0, pageWidth, 45, 'F');

    // ロゴを追加
    let logoBase64 = null;
    try {
      logoBase64 = await loadImageAsBase64(logo);
      // pdf.addImage(logoBase64, 'PNG', margin - 11, 16, 16);
    } catch (e) {
      console.warn('ロゴの読み込みに失敗しました:', e);
    }

    // ヘッダーを描画する関数
    const drawHeader = () => {
      // ヘッダー背景（プライマリカラー）
      pdf.setFillColor(13, 110, 253);
      pdf.rect(0, 0, pageWidth, 45, 'F');

      // ロゴを追加
      if (logoBase64) {
        pdf.addImage(logoBase64, 'PNG', margin - 11, 4, 16, 16);
      }

      // アプリ名
      pdf.setFont("NotoSansJP", "normal");
      pdf.setFontSize(16);
      pdf.setTextColor(255, 255, 255);
      pdf.text('行政秘書', margin + 7, 15);
    };
    drawHeader();

    // タイトル（白文字、中央寄せ）
    pdf.setFontSize(18);
    pdf.setFont("NotoSansJP", "normal");
    const titleLines = pdf.splitTextToSize(data.title, contentWidth - 20);
    const titleHeight = titleLines.length * 8;
    pdf.text(titleLines, pageWidth / 2, 30, { align: 'center' });
    
    yPos = 50;

    // 日付
    pdf.setFontSize(9);
    pdf.setTextColor(100, 100, 100);
    const today = new Date().toLocaleDateString('ja-JP', { 
      year: 'numeric', 
      month: 'long', 
      day: 'numeric' 
    });
    pdf.text(`発行日: ${today}`, pageWidth - margin, yPos, { align: 'right' });
    yPos += 10;

    // 区切り線
    pdf.setDrawColor(200, 200, 200);
    pdf.setLineWidth(0.5);
    pdf.line(margin, yPos, pageWidth - margin, yPos);
    yPos += 10;

    // セクション1: 概要
    pdf.setFillColor(240, 248, 255); // 淡い青背景
    pdf.roundedRect(margin, yPos, contentWidth, 15, 2, 2, 'F');
    
    pdf.setFontSize(12);
    pdf.setTextColor(13, 110, 253);
    pdf.setFont("NotoSansJP", "normal");
    pdf.text('📋 概要', margin + 5, yPos + 9);
    yPos += 20;

    // 内容テキスト
    pdf.setFontSize(10);
    pdf.setTextColor(50, 50, 50);
    pdf.setFont("NotoSansJP", "normal");
    const contentLines = pdf.splitTextToSize(data.content, contentWidth - 10);
    pdf.text(contentLines, margin + 5, yPos);
    yPos += contentLines.length * 6 + 15;

    // セクション2: 手続きの流れ
    if (data.steps && data.steps.length > 0) {
      // 改ページチェック
      if (yPos + 50 > pageHeight - 20) {
        pdf.addPage();
        drawHeader(); // 新しいページにヘッダーを追加
        yPos = 50; // ヘッダー分の余白を確保
      }

      pdf.setFillColor(240, 248, 255);
      pdf.roundedRect(margin, yPos, contentWidth, 15, 2, 2, 'F');
      
      pdf.setFontSize(12);
      pdf.setTextColor(13, 110, 253);
      pdf.text('✅ 手続きの流れ', margin + 5, yPos + 9);
      yPos += 20;

      data.steps.forEach((step, index) => {
        // 改ページチェック
        if (yPos > pageHeight - 30) {
          pdf.addPage();
          drawHeader(); // 新しいページにヘッダーを追加
          yPos = 50;
        }

        // ステップ番号の円
        pdf.setFillColor(13, 110, 253);
        pdf.circle(margin + 7, yPos + 3, 4, 'F');
        
        pdf.setFontSize(9);
        pdf.setTextColor(255, 255, 255);
        pdf.text(`${index + 1}`, margin + 7, yPos + 4.5, { align: 'center' });

        // ステップテキスト
        pdf.setFontSize(10);
        pdf.setTextColor(50, 50, 50);
        pdf.setFont("NotoSansJP", "normal");
        const stepLines = pdf.splitTextToSize(step, contentWidth - 25);
        pdf.text(stepLines, margin + 15, yPos + 5);
        yPos += Math.max(stepLines.length * 6, 10) + 5;
      });

      yPos += 10;
    }

    // セクション3: 参照元
    if (data.urls && data.urls.length > 0) {
      // 改ページチェック
      if (yPos + 30 > pageHeight - 20) {
        pdf.addPage();
        drawHeader(); // 新しいページにヘッダーを追加
        yPos = 50;
      }

      pdf.setFillColor(240, 248, 255);
      pdf.roundedRect(margin, yPos, contentWidth, 15, 2, 2, 'F');
      
      pdf.setFontSize(12);
      pdf.setTextColor(13, 110, 253);
      pdf.text('🔗 参照元', margin + 5, yPos + 9);
      yPos += 20;

      pdf.setFontSize(9);
      pdf.setTextColor(0, 0, 255);
      pdf.setFont("NotoSansJP", "normal");
      
      data.urls.forEach(url => {
        // 改ページチェック
        if (yPos > pageHeight - 20) {
          pdf.addPage();
          drawHeader(); // 新しいページにヘッダーを追加
          yPos = 50;
        }

        // リンクアイコン風
        pdf.setDrawColor(0, 0, 255);
        pdf.setLineWidth(0.3);
        pdf.rect(margin + 2, yPos - 2, 3, 3);
        
        const urlLines = pdf.splitTextToSize(url, contentWidth - 15);
        pdf.textWithLink(urlLines[0], margin + 8, yPos + 1, { url });
        yPos += 7;
      });
    }

    // フッター
    const footerY = pageHeight - 15;
    pdf.setDrawColor(200, 200, 200);
    pdf.line(margin, footerY, pageWidth - margin, footerY);
    
    pdf.setFontSize(8);
    pdf.setTextColor(150, 150, 150);
    pdf.text(
      '© 2026 Gov-Secretary Project. All rights reserved.',
      pageWidth / 2,
      footerY + 5,
      { align: 'center' }
    );

    // ページ番号
    const pageCount = pdf.internal.getNumberOfPages();
    for (let i = 1; i <= pageCount; i++) {
      pdf.setPage(i);
      pdf.setFontSize(8);
      pdf.setTextColor(150, 150, 150);
      pdf.text(`${i} / ${pageCount}`, pageWidth - margin, footerY + 5, { align: 'right' });
    }

    pdf.save(`${data.title}.pdf`);
  } catch (error) {
    console.error('PDF generation error:', error);
    alert('PDFの生成中にエラーが発生しました');
  }
};

// --- Components ---

const Header = ({ onNavigate, mode, setMode }) => (
  <header className="navbar navbar-expand-lg navbar-dark bg-primary mb-1 shadow-sm">
    <div className="container" style={{ maxWidth: "98%" }}>
      <a className="navbar-brand fw-bold d-flex align-items-center" href="#" onClick={(e) => { e.preventDefault(); onNavigate('home'); }}>
        <img src={logo} alt="Logo" width="70" height="70" className="d-inline-block align-text-top me-2" />
        行政秘書
      </a>

      <div className="d-flex bg-white rounded-pill p-1">
        <button
          className={`btn btn-sm rounded-pill px-3 ${mode === 'search' ? 'btn-primary' : 'btn-light text-muted'}`}
          onClick={() => setMode('search')}
        >
          検索
        </button>
        <button
          className={`btn btn-sm rounded-pill px-3 ${mode === 'chat' ? 'btn-primary' : 'btn-light text-muted'}`}
          onClick={() => setMode('chat')}
        >
          チャット
        </button>
      </div>
    </div>
  </header>
);

const HomeScreen = ({ onNavigate, municipality, setMunicipality }) => (
  <div className="text-center animate-fade-in">
    <h2 className="mb-4 fw-bold text-primary">
      自治体を検索してください
    </h2>
    <div className="row justify-content-center">
      <div className="col-md-6">
        <div className="input-group input-group-lg mb-3 shadow-sm p-2 bg-white rounded">
          <span className="input-group-text bg-white text-muted border-end-0">{supportIcons.search}</span>
          <input
            type="text"
            className="form-control border-start-0 ps-4"
            placeholder="例：東京都千代田区"
            aria-label="Search Municipality"
            value={municipality}
            onChange={(e) => setMunicipality(e.target.value)}
          />
        </div>
        <button
          className="btn btn-primary btn-lg w-100 shadow-sm"
          onClick={() => {
            onNavigate('domain');
            console.log(`municipality Updated: ${municipality}`);
          }}
          disabled={!municipality || municipality.length === 0}
        >
          次へ進む
        </button>
      </div>
    </div>
    <div className="mt-5 text-start mx-auto features-container">
      {['first', 'second', 'third'].map((key) => (
        <div key={key} className="feature-item d-flex align-items-start">
          <div className="me-3 text-primary">
            {featureIcons[key]}
          </div>
          <div>
            <h4 className="fw-bold text-secondary mb-1">{catchCopies[key]}</h4>
            <p className="text-muted mb-0">{subCopies[key]}</p>
          </div>
        </div>
      ))}
    </div>
  </div>
);

const DomainScreen = ({ onNavigate, onSelectDomain }) => (
  <div className="animate-fade-in">
    <h2 className="mb-4 text-center fw-bold text-primary">手続きのカテゴリーを選択</h2>
    <div className="row g-4">
      {categories.map((cat) => (
        <div key={cat.id} className="col-6 col-md-3">
          <div
            className="card h-100 text-center p-4 shadow-sm hover-card cursor-pointer border-0"
            onClick={() => {
              onSelectDomain(cat.id);
              console.log(`Domain Selected: ${cat.id}`);
            }}
          >
            <div className="display-4 mb-2">{cat.icon}</div>
            <h5 className="card-title fw-bold text-black-50">{cat.title}</h5>
          </div>
        </div>
      ))}
    </div>
    <div className="mt-4 text-center">
      <button
        className="btn btn-outline-secondary"
        onClick={() => {
          onNavigate('home');
          // callTestAPI();
        }}
      >
        戻る
      </button>
    </div>
  </div>
);

const InputScreen = ({ form, setForm, onNavigate, onSubmit }) => {
  const [activeAccordion, setActiveAccordion] = useState('');

  const update = (key, value) => {
    setForm({ ...form, [key]: value });
  };

  const toggleAccordion = (id) => {
    setActiveAccordion(prev => prev === id ? '' : id);
  };

  const renderAgeInputs = (countKey, prefix) => {
    const count = parseInt(form[countKey] || 0);
    if (count <= 0) return null;

    return (
      <div className="d-flex flex-wrap gap-2 mt-2 animate-fade-in">
        {Array.from({ length: count }).map((_, i) => (
          <div key={i} className="input-group input-group-sm" style={{ width: '140px' }}>
            <span className="input-group-text bg-light">{i + 1}人目</span>
            <input
              type="number"
              className="form-control"
              placeholder="年齢"
              min="0"
              max="120"
              onChange={(e) => update(`${prefix}_age_${i + 1}`, e.target.value)}
            />
            <span className="input-group-text bg-white">歳</span>
          </div>
        ))}
      </div>
    );
  };

  return (
    <div className="animate-fade-in container">
      <h2 className="mb-4 text-center fw-bold text-primary">
        ご自身の情報を入力<br />（スキップ可）
      </h2>

      <div className="accordion" id="profileAccordion">
        {/* STEP 1: 基本情報 */}
        <div className="accordion-item">
          <h2 className="accordion-header">
            <button
              className={`accordion-button ${activeAccordion === 'basicInfo' ? '' : 'collapsed'}`}
              type="button"
              onClick={() => toggleAccordion('basicInfo')}
            >
              基本情報
            </button>
          </h2>
          <div id="basicInfo" className={`accordion-collapse custom-collapse ${activeAccordion === 'basicInfo' ? 'show' : ''}`}>
            <div className={`accordion-body ${activeAccordion === 'basicInfo' ? 'show' : ''}`}>
              <p className="small text-muted mb-3">世帯構成人数と、それぞれの年齢を入力してください。</p>
              {/* 夫婦（本人含） */}
              <div className="mb-4 border-bottom pb-3">
                <div className="d-flex justify-content-between align-items-center">
                  <label className="form-label mb-0">本人</label>
                  <div className="input-group" style={{ width: '150px' }}>
                    <input
                      type="number"
                      className="form-control"
                      min="0"
                      max="120"
                      placeholder="0"
                      onChange={(e) => update("user_age", e.target.value)}
                    />
                    <span className="input-group-text bg-white text-muted">歳</span>
                  </div>
                </div>
              </div>
              <div className="mb-4 border-bottom pb-3">
                <div className="d-flex justify-content-between align-items-center">
                  <label className="form-label mb-0">配偶者・パートナー</label>
                  <div className="input-group" style={{ width: '150px' }}>
                    <input
                      type="number"
                      className="form-control"
                      min="0"
                      max="120"
                      placeholder="不在時空欄"
                      onChange={(e) => update("partner_age", e.target.value)}
                    />
                    <span className="input-group-text bg-white text-muted">歳</span>
                  </div>
                </div>
              </div>
              {/* 子供 */}
              <div className="mb-4 border-bottom pb-3">
                <div className="d-flex justify-content-between align-items-center">
                  <label className="form-label mb-0">子供</label>
                  <div className="input-group" style={{ width: '150px' }}>
                    <input
                      type="number"
                      className="form-control"
                      min="0"
                      placeholder="0"
                      onChange={(e) => update("child_count", e.target.value)}
                    />
                    <span className="input-group-text bg-white text-muted">人</span>
                  </div>
                </div>
                {renderAgeInputs("child_count", "child")}
              </div>
              {/* 親 */}
              <div className="mb-3">
                <div className="d-flex justify-content-between align-items-center">
                  <label className="form-label mb-0">親（同居）</label>
                  <div className="input-group" style={{ width: '150px' }}>
                    <input
                      type="number"
                      className="form-control"
                      min="0"
                      max="4"
                      placeholder="0"
                      onChange={(e) => update("parent_count", e.target.value)}
                    />
                    <span className="input-group-text bg-white text-muted">人</span>
                  </div>
                </div>
                {renderAgeInputs("parent_count", "parent")}
              </div>
            </div>
          </div>
        </div>

        {/* STEP 2: ライフイベント */}
        <div className="accordion-item">
          <h2 className="accordion-header">
            <button
              className={`accordion-button ${activeAccordion === 'lifeEvent' ? '' : 'collapsed'}`}
              type="button"
              onClick={() => toggleAccordion('lifeEvent')}
            >
              ライフイベント
            </button>
          </h2>
          <div id="lifeEvent" className={`accordion-collapse custom-collapse ${activeAccordion === 'lifeEvent' ? 'show' : ''}`}>
            <div className={`accordion-body ${activeAccordion === 'lifeEvent' ? 'show' : ''}`}>
              <div className="mb-3">
                <label className="form-label">今後の転居予定</label>
                <select
                  className="form-select"
                  onChange={(e) => update("moving", e.target.value)}
                >
                  <option value="">なし / 未定</option>
                  <option>半年以内</option>
                  <option>1年以内</option>
                </select>
              </div>

              <div className="mb-3">
                <label className="form-label">妊娠・出産予定</label>
                <select
                  className="form-select"
                  onChange={(e) => update("pregnancy", e.target.value)}
                >
                  <option value="">特になし / 未定</option>
                  <option>半年以内に出産予定</option>
                  <option>1年以内に出産予定</option>
                </select>
              </div>

            </div>
          </div>
        </div>

        {/* STEP 3: 就労・収入 */}
        <div className="accordion-item">
          <h2 className="accordion-header">
            <button
              className={`accordion-button ${activeAccordion === 'workInfo' ? '' : 'collapsed'}`}
              type="button"
              onClick={() => toggleAccordion('workInfo')}
            >
              就労・収入
            </button>
          </h2>
          <div id="workInfo" className={`accordion-collapse custom-collapse ${activeAccordion === 'workInfo' ? 'show' : ''}`}>
            <div className={`accordion-body ${activeAccordion === 'workInfo' ? 'show' : ''}`}>
              <div className="mb-3">
                <label className="form-label">就労状況</label>
                <select
                  className="form-select"
                  onChange={(e) => update("employment", e.target.value)}
                >
                  <option value="">選択しない</option>
                  <option>就業中</option>
                  <option>育休・休職中</option>
                  <option>失業中</option>
                  <option>再就職予定</option>
                </select>
              </div>
              <div className="mb-3">
                <label className="form-label">現在の世帯年収</label>
                <input
                  className="input-group form-control"
                  onChange={(e) => update("income_t0", e.target.value)}
                  placeholder="例：300万円"
                  type="number"
                  min="0"
                />
              </div>
              <div className="mb-3">
                <label className="form-label">1年後の世帯年収</label>
                <input
                  className="input-group form-control"
                  onChange={(e) => update("income_t1", e.target.value)}
                  placeholder="例：300万円"
                  type="number"
                  min="0"
                />
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Actions */}
      <div className="mt-4 text-center d-flex justify-content-center gap-3">
        <button className="btn btn-outline-secondary w-100 h-100" onClick={() => onNavigate("domain")}>
          戻る
        </button>
        <button
          className="btn btn-primary w-100 h-100"
          onClick={() => {
            onSubmit();
            onNavigate("info", form);
          }}
        >
          制度を探す
        </button>
      </div>
    </div>
  );
};

const InfoScreen = ({ onNavigate, searchResults }) => {
  // searchResultsがない場合はinfoDataを使用（フォールバック）
  const dataToDisplay = searchResults || infoData;

  return (
    <div className="animate-fade-in container">
      <h2 className="mb-4 text-center fw-bold text-primary">
        おススメの手続き情報
      </h2>

      {Object.entries(dataToDisplay).map(([key, data]) => (
        <div key={key} className="card shadow-sm border-0 mb-4">
          <div className="card-body text-center p-3">
            <div className="align-items-center mb-4">
              <h3 className="card-title text-primary fw-bold mb-0">{data.title}</h3>
            </div>

            <p className="card-text lead mb-4">{data.content}</p>

            {data.steps && data.steps.length > 0 && (
              <div className="bg-light p-2 rounded-3">
                <h5 className="fw-bold mb-3 text-secondary">手続きの流れ:</h5>
                <ul className="list-group list-group-flush bg-transparent">
                  {data.steps.map((step, index) => (
                    <li key={index} className="list-group-item px-0 bg-transparent border-bottom-0 pb-2">
                      <span className="badge bg-primary rounded-pill me-2">{index + 1}</span>
                      {step}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {data.urls && data.urls.length > 0 && (
              <div className="mt-4">
                <p className="small text-muted mb-2">参照元</p>
                <div className="d-flex justify-content-center gap-3">
                  {data.urls.map((url, index) => (
                    <a
                      key={index}
                      href={url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="btn btn-white rounded-circle shadow-sm border d-flex align-items-center justify-content-center hover-card"
                      style={{ width: '60px', height: '60px' }}
                      title={url}
                    >
                      <img
                        src={`https://www.google.com/s2/favicons?domain=${new URL(url).hostname}&sz=64`}
                        alt="公式サイト"
                        width="32"
                        height="32"
                      />
                    </a>
                  ))}
                </div>
              </div>
            )}

            <div className="mt-4">
              <button 
                className="btn btn-outline-primary"
                onClick={() => downloadPDF(key, data)}
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" className="bi bi-download me-2" viewBox="0 0 16 16">
                  <path d="M.5 9.9a.5.5 0 0 1 .5.5v2.5a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-2.5a.5.5 0 0 1 1 0v2.5a2 2 0 0 1-2 2H2a2 2 0 0 1-2-2v-2.5a.5.5 0 0 1 .5-.5"/>
                  <path d="M7.646 11.854a.5.5 0 0 0 .708 0l3-3a.5.5 0 0 0-.708-.708L8.5 10.293V1.5a.5.5 0 0 0-1 0v8.793L5.354 8.146a.5.5 0 1 0-.708.708l3 3z"/>
                </svg>
                PDFダウンロード
              </button>
            </div>
          </div>
        </div>
      ))}

      <div className="d-flex gap-3 flex-row justify-content-center mt-5 mb-5">
        <button className="btn btn-outline-secondary w-100 h-100" onClick={() => onNavigate('input')}>
          戻る
        </button>
        {/* <button className="btn btn-primary w-100 h-100">
          ダウンロード
        </button> */}
      </div>
    </div>
  );
};


const ProgressStepper = ({ currentStep }) => {
  const steps = [
    {
      number: 1,
      // label: '自治体選択'
    },
    {
      number: 2,
      // label: 'カテゴリー選択'
    },
    {
      number: 3,
      // label: '情報入力'
    },
    {
      number: 4,
      // label: 'チェックリスト生成'
    },
  ];

  // 進捗率の計算 (0% ~ 100%)
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
              <div className={`small mt-0 fw-bold ${isActive ? 'text-primary' : 'text-muted'}`}>
                {step.label}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

const Loading = ({ message = "webを検索しています･･" }) => {
  const [statusText, setStatusText] = useState("処理中");

  useEffect(() => {
    const timer = setTimeout(() => {
      setStatusText("少々お待ちください");
    }, 5000);

    return () => clearTimeout(timer);
  }, []);

  return (
    <div className="loading-overlay startup">
      <div className="loading-card text-center p-4">
        <div className="spinner-border text-primary mb-3" role="status" />
        <div className="fw-semibold text-dark mb-1">{message}</div>
        <div className="text-muted small loading-dots">
          {statusText}
        </div>
      </div>
    </div>
  );
};

const Footer = () => (
  <footer className="bg-white text-center py-3 mt-auto border-top text-muted d-flex flex-column align-items-center">
    <small>&copy; 2026 Gov-Secretary Project. All rights reserved.</small>
    <small>入力いただいた個人情報は保存しません</small>
  </footer>
);

// --- Main App Component ---

function App() {
  const [currentScreen, setCurrentScreen] = useState('home');
  const initialMode = import.meta.env.VITE_DEFAULT_MODE === 'chat' ? 'chat' : 'search';
  const [mode, setMode] = useState(initialMode); // 'search' | 'chat'
  const [isLoading, setIsLoading] = useState(false);

  const [appData, setAppData] = useState({
    municipality: '',
    domain: '',
    formData: {},
    searchResults: null
  });

  const updateAppData = (key, value) => {
    setAppData(prev => ({ ...prev, [key]: value }));
  };

  const navigateTo = (screen, data = {}) => {
    if (Object.keys(data).length > 0) {
      setAppData(prev => ({
        ...prev,
        formData: { ...prev.formData, ...data }
      }));
    }
    setCurrentScreen(screen);
    window.scrollTo(0, 0);
  };

  const submitData = async () => {
    // inputs配列を作成
    const inputs = {};
    Object.entries(appData.formData).forEach(([key, value], index) => {
      const labelMap = {
        user_age: '本人の年齢',
        partner_age: '配偶者・パートナーの年齢',
        child_count: '子供の人数',
        parent_count: '親の人数',
        pregnancy: '妊娠・出産予定',
        moving: '今後の転居予定',
        employment: '就労状況',
        income_t0: '現在の世帯年収',
        income_t1: '1年後の世帯年収',
      };

      let label = labelMap[key];
      if (!label) {
        if (key.includes('child_age_')) label = `子供 ${key.split('_')[2]}人目 年齢`;
        if (key.includes('parent_age_')) label = `親 ${key.split('_')[2]}人目 年齢`;
      }

      inputs[index.toString()] = {
        key: key,
        label: label || key,
        value: value
      };
    });

    const payload = {
      municipality: appData.municipality,
      domain: appData.domain,
      inputs: inputs
    };

    console.log("Sending payload:", payload);

    setIsLoading(true);
    try {
      const result = await callSearchAPI(payload);

      if (result.success) {
        console.log("Search successful:", result.data);
        updateAppData('searchResults', result.data);
      } else {
        console.error("Search failed:", result.error);
        alert(`検索に失敗しました: ${result.message}`);
      }
    } catch (e) {
      console.error("API call failed:", e);
      alert("サーバーとの通信に失敗しました");
    } finally {
      setIsLoading(false);
    }
  };

  const getStepNumber = (screen) => {
    switch (screen) {
      case 'home': return 1;
      case 'domain': return 2;
      case 'input': return 3;
      case 'info': return 4;
      default: return 0;
    }
  };

  const currentStep = getStepNumber(currentScreen);

  return (
    <div className="d-flex flex-column min-vh-100 bg-light">
      <Header onNavigate={navigateTo} mode={mode} setMode={setMode} />

      <main className="flex-grow-1" style={{ position: 'relative' }}>
        {mode === 'chat' ? (
          <div className="container py-4 fade-in">
            <div className="card shadow-sm border-0" style={{ height: '80vh' }}>
              <ChatScreen
                municipality={appData.municipality}
                setMunicipality={(val) => updateAppData('municipality', val)}
                onSelectDomain={(val) => updateAppData('domain', val)}
                categories={categories}
                form={appData.formData}
                setForm={(newForm) => updateAppData('formData', newForm)}
                setSearchResults={(val) => updateAppData('searchResults', val)}
                callAssistantAPI={callAssistantAPI}
                downloadPDF={downloadPDF}
              />
            </div>
          </div>
        ) : (
          <div className="container py-4">
            {(
              <ProgressStepper currentStep={currentStep} />
            )}

            {currentScreen === 'home' && (
              <HomeScreen
                onNavigate={navigateTo}
                municipality={appData.municipality}
                setMunicipality={(val) => updateAppData('municipality', val)}
              />
            )}

            {currentScreen === 'domain' && (
              <DomainScreen
                onNavigate={navigateTo}
                domain={appData.domain}
                onSelectDomain={(id) => {
                  updateAppData('domain', id);
                  navigateTo('input');
                }}
              />
            )}

            {currentScreen === 'input' && (
              <InputScreen
                form={appData.formData}
                setForm={(newForm) => updateAppData('formData', newForm)}
                onNavigate={navigateTo}
                onSubmit={submitData}
              />
            )}

            {currentScreen === 'info' && (
              <InfoScreen
                onNavigate={navigateTo}
                searchResults={appData.searchResults}
              />
            )}

          </div>
        )}

        {isLoading && <Loading />}
      </main>

      <Footer />
    </div>
  );
}

export default App;
