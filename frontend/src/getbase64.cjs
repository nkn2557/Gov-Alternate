// getbase64.js
const fs = require("fs");

const fontFilePath = "assets/NotoSansJP-Regular.ttf"; // 元のフォントファイル
const outputFilePath = "assets/NotoSansJP-Regular-base64.txt"; // 出力先

fs.readFile(fontFilePath, (err, data) => {
  if (err) {
    console.error("フォントファイルの読み込みに失敗しました:", err);
    return;
  }

  const base64Data = data.toString("base64");
  fs.writeFile(outputFilePath, base64Data, (err) => {
    if (err) {
      console.error("Base64ファイルの書き込みに失敗しました:", err);
      return;
    }
    console.log("Base64変換が完了しました! ファイル:", outputFilePath);
  });
});
