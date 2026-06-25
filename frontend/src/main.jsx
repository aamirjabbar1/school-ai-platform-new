import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.jsx';
import './index.css';
// KaTeX styles for rendered math/chemistry formulas, plus the mhchem extension
// that adds \ce{} support for chemical equations.
import 'katex/dist/katex.min.css';
import 'katex/contrib/mhchem';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
