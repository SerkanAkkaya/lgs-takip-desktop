"""
LGS Hazırlık Takip Programı
Desktop uygulaması - Soru çözüm takibi ve analiz
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
import sys
import ttkbootstrap as ttkb
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox
from datetime import datetime, timedelta, date
import matplotlib

matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
import locale
import threading
import json as json_module
import re
import pdfplumber

# Türkçe locale ayarla
try:
    locale.setlocale(locale.LC_ALL, "tr_TR.UTF-8")
except Exception:
    try:
        locale.setlocale(locale.LC_ALL, "Turkish_Turkey.1254")
    except Exception:
        pass

# Matplotlib Türkçe karakter desteği
plt.rcParams["font.family"] = ["Segoe UI", "Arial", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

import database as db
import sync

# Sabitler
DERSLER = db.DERSLER
DERS_RENKLERI = db.DERS_RENKLERI

AY_ISIMLERI = {
    1: "Ocak", 2: "Şubat", 3: "Mart", 4: "Nisan",
    5: "Mayıs", 6: "Haziran", 7: "Temmuz", 8: "Ağustos",
    9: "Eylül", 10: "Ekim", 11: "Kasım", 12: "Aralık"
}

APP_VERSION = "1.1.0"
APP_DEVELOPER = "Serkan Akkaya"

# Hızlı ve güncel varsayılan Gemini modeli (thinking ağırlıklı alias'lar masaüstünde yavaş kalıyor).
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"


class LGSTakipApp:
    def __init__(self):
        # Veritabanını başlat
        db.init_db()

        # Ana pencere
        self.root = ttkb.Window(
            title="📚 LGS Hazırlık Takip Programı",
            themename="cosmo",
            size=(1200, 800),
            minsize=(1000, 700),
        )
        self.root.place_window_center()

        # Stil ayarları
        self.style = ttkb.Style()

        # Menü çubuğu
        self._build_menu()

        self._build_ui()

        # Açılışta otomatik senkronizasyon (arka plan thread'inde, UI'ı bloke etmez)
        self.root.after(500, self._baslangic_senkronizasyonu)

    def _build_menu(self):
        """Menü çubuğunu oluştur."""
        menubar = tk.Menu(self.root)
        self.root.configure(menu=menubar)

        # Ayarlar menüsü
        ayarlar_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Ayarlar", menu=ayarlar_menu)
        ayarlar_menu.add_command(label="🔑 AI API Ayarları", command=self._api_key_dialog)

        # Yardım menüsü
        yardim_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Yardım", menu=yardim_menu)
        yardim_menu.add_command(label="Hakkında", command=self._hakkinda_goster)

    def _hakkinda_goster(self):
        """Hakkında penceresini göster."""
        hakkinda = tk.Toplevel(self.root)
        hakkinda.title("Hakkında")
        hakkinda.geometry("420x280")
        hakkinda.resizable(False, False)
        hakkinda.transient(self.root)
        hakkinda.grab_set()

        # Pencereyi ortala
        hakkinda.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - 420) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 280) // 2
        hakkinda.geometry(f"+{x}+{y}")

        frame = ttkb.Frame(hakkinda, padding=25)
        frame.pack(fill=BOTH, expand=True)

        ttkb.Label(frame, text="📚 LGS Hazırlık Takip Programı",
                   font=("Segoe UI", 14, "bold"), bootstyle="primary").pack(pady=(0, 5))

        ttkb.Label(frame, text=f"Sürüm {APP_VERSION}",
                   font=("Segoe UI", 11), bootstyle="secondary").pack()

        ttkb.Separator(frame, bootstyle="secondary").pack(fill=X, pady=12)

        ttkb.Label(frame,
                   text="LGS sınavına hazırlanan öğrenciler için günlük soru takibi,\n"
                        "sınav analizi ve performans değerlendirme uygulamasıdır.",
                   font=("Segoe UI", 10), justify=CENTER, wraplength=370).pack(pady=(0, 10))

        ttkb.Label(frame, text=f"Geliştirici: {APP_DEVELOPER}",
                   font=("Segoe UI", 10, "bold")).pack()

        ttkb.Label(frame, text=f"Veritabanı Sürümü: v{db.DB_VERSION}",
                   font=("Segoe UI", 9), bootstyle="secondary").pack(pady=(3, 0))

        ttkb.Button(frame, text="Tamam", command=hakkinda.destroy,
                    bootstyle="primary", width=12).pack(pady=(12, 0))

    def _api_key_dialog(self):
        """API anahtarı girişi/güncelleme penceresi (Gemini + OpenAI)."""
        dialog = tk.Toplevel(self.root)
        dialog.title("🔑 AI API Ayarları")
        dialog.geometry("540x480")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - 540) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 480) // 2
        dialog.geometry(f"+{x}+{y}")

        frame = ttkb.Frame(dialog, padding=20)
        frame.pack(fill=BOTH, expand=True)

        ttkb.Label(frame, text="🤖 AI API Ayarları",
                   font=("Segoe UI", 13, "bold"), bootstyle="primary").pack(pady=(0, 10))

        # ── Sağlayıcı Seçimi ──
        provider_frame = ttkb.Labelframe(frame, text="AI Sağlayıcı", padding=10, bootstyle="info")
        provider_frame.pack(fill=X, pady=(0, 10))

        mevcut_provider = db.oku_ayar("ai_provider", "gemini")
        provider_var = tk.StringVar(value=mevcut_provider)

        def on_provider_change():
            p = provider_var.get()
            if p == "gemini":
                info_label.configure(text="Ücretsiz API anahtarı: aistudio.google.com\nModel: gemini-2.5-flash (Hızlı, ücretsiz kotayla)")
                key_var.set(db.oku_ayar("gemini_api_key", ""))
            else:
                info_label.configure(text="API anahtarı: platform.openai.com → API Keys\nModel: gpt-4o-mini (Çok ucuz ~$0.003/analiz)")
                key_var.set(db.oku_ayar("openai_api_key", ""))
            _durum_guncelle()

        r_frame = ttkb.Frame(provider_frame)
        r_frame.pack(fill=X)
        ttkb.Radiobutton(r_frame, text="🌟 Google Gemini (Ücretsiz)", variable=provider_var,
                         value="gemini", command=on_provider_change, bootstyle="info").pack(side=LEFT, padx=10)
        ttkb.Radiobutton(r_frame, text="💠 OpenAI (ChatGPT)", variable=provider_var,
                         value="openai", command=on_provider_change, bootstyle="success").pack(side=LEFT, padx=10)

        info_label = ttkb.Label(provider_frame, text="", font=("Segoe UI", 8),
                               bootstyle="secondary", wraplength=480)
        info_label.pack(anchor=W, pady=(5, 0))

        ttkb.Separator(frame, bootstyle="secondary").pack(fill=X, pady=8)

        # ── API Anahtarı ──
        ttkb.Label(frame, text="API Anahtarı:", font=("Segoe UI", 10, "bold")).pack(anchor=W, pady=(5, 3))

        key_var = tk.StringVar()
        key_entry = ttkb.Entry(frame, textvariable=key_var, font=("Segoe UI", 10), show="•", width=55)
        key_entry.pack(fill=X, pady=(0, 3))

        goster_var = tk.BooleanVar(value=False)
        def toggle_goster():
            key_entry.configure(show="" if goster_var.get() else "•")
        ttkb.Checkbutton(frame, text="Anahtarı göster", variable=goster_var,
                         command=toggle_goster, bootstyle="secondary").pack(anchor=W)

        durum_label = ttkb.Label(frame, text="", font=("Segoe UI", 9))
        durum_label.pack(pady=(5, 0))

        def _durum_guncelle():
            k = key_var.get().strip()
            if k:
                durum_label.configure(text="✅ API anahtarı kayıtlı", bootstyle="success")
            else:
                durum_label.configure(text="⚠️ API anahtarı girilmemiş", bootstyle="warning")

        # Model seçimi
        ttkb.Separator(frame, bootstyle="secondary").pack(fill=X, pady=8)
        model_frame = ttkb.Frame(frame)
        model_frame.pack(fill=X)
        ttkb.Label(model_frame, text="Model:", font=("Segoe UI", 10, "bold")).pack(side=LEFT)
        mevcut_model = db.oku_ayar("ai_model", "")
        model_var = tk.StringVar(value=mevcut_model)
        model_entry = ttkb.Entry(model_frame, textvariable=model_var, font=("Segoe UI", 9), width=30)
        model_entry.pack(side=LEFT, padx=(8, 5))
        ttkb.Label(model_frame, text="(boş=varsayılan)", font=("Segoe UI", 8),
                   bootstyle="secondary").pack(side=LEFT)

        # Butonlar
        btn_frame = ttkb.Frame(frame)
        btn_frame.pack(pady=(12, 0))

        def kaydet():
            key = key_var.get().strip()
            p = provider_var.get()
            if key:
                db.kaydet_ayar("ai_provider", p)
                db.kaydet_ayar(f"{p}_api_key", key)
                m = model_var.get().strip()
                db.kaydet_ayar("ai_model", m)
                prov_name = "Gemini" if p == "gemini" else "OpenAI"
                messagebox.showinfo("Başarılı",
                    f"{prov_name} API anahtarı kaydedildi.\n"
                    f"Artık AI Analiz sekmesini kullanabilirsiniz.", parent=dialog)
                dialog.destroy()
            else:
                durum_label.configure(text="❌ Lütfen API anahtarını girin", bootstyle="danger")

        def sil():
            p = provider_var.get()
            db.kaydet_ayar(f"{p}_api_key", "")
            key_var.set("")
            durum_label.configure(text="🗑️ API anahtarı silindi", bootstyle="warning")

        ttkb.Button(btn_frame, text="💾 Kaydet", command=kaydet,
                    bootstyle="success", width=14).pack(side=LEFT, padx=5)
        ttkb.Button(btn_frame, text="🗑️ Sil", command=sil,
                    bootstyle="danger-outline", width=10).pack(side=LEFT, padx=5)
        ttkb.Button(btn_frame, text="İptal", command=dialog.destroy,
                    bootstyle="secondary", width=10).pack(side=LEFT, padx=5)

        # İlk yükleme
        on_provider_change()

    def _build_ui(self):
        """Ana arayüzü oluştur."""
        # Başlık
        header_frame = ttkb.Frame(self.root, padding=10)
        header_frame.pack(fill=X)

        ttkb.Label(
            header_frame,
            text="📚 LGS Hazırlık Takip Programı",
            font=("Segoe UI", 18, "bold"),
            bootstyle="primary",
        ).pack(side=LEFT)

        # Sağ taraf: Tarih + Veri butonları
        right_frame = ttkb.Frame(header_frame)
        right_frame.pack(side=RIGHT)

        # Senkronizasyon butonu (ana pencerede, her zaman görünür)
        self.sync_button = ttkb.Button(
            right_frame,
            text="🔄 Sync Remote",
            command=self._sync_remote_clicked,
            bootstyle="success",
        )
        self.sync_button.pack(side=RIGHT, padx=(3, 10))

        ttkb.Button(
            right_frame,
            text="📥 İçe Aktar",
            command=self._import_data,
            bootstyle="info-outline",
        ).pack(side=RIGHT, padx=3)

        ttkb.Button(
            right_frame,
            text="📤 Dışa Aktar",
            command=self._export_data,
            bootstyle="info-outline",
        ).pack(side=RIGHT, padx=3)

        ttkb.Label(
            right_frame,
            text=f"📅 {datetime.now().strftime('%d.%m.%Y')}  ",
            font=("Segoe UI", 12),
            bootstyle="secondary",
        ).pack(side=RIGHT, padx=(0, 10))

        # DB konum bilgisi + senkronizasyon durumu (küçük yazı)
        db_info_frame = ttkb.Frame(self.root)
        db_info_frame.pack(fill=X, padx=12)
        ttkb.Label(
            db_info_frame,
            text="💾 Veritabanı: Yerel SQLite (çevrimdışı çalışır) • ☁️ Neon ile senkronize",
            font=("Segoe UI", 8),
            bootstyle="secondary",
        ).pack(side=LEFT)
        self.sync_status_label = ttkb.Label(
            db_info_frame,
            text="",
            font=("Segoe UI", 8),
            bootstyle="secondary",
        )
        self.sync_status_label.pack(side=RIGHT)
        self._sync_status_guncelle()

        # Notebook (Tab kontrolü)
        self.notebook = ttkb.Notebook(self.root, bootstyle="primary")
        self.notebook.pack(fill=BOTH, expand=True, padx=10, pady=(0, 10))

        # Sekmeler
        self._build_veri_girisi_tab()
        self._build_tablo_tab()
        self._build_grafik_tab()
        self._build_trend_tab()
        self._build_sinav_tab()
        self._build_ai_tab()
        self._build_karne_tab()

    # =====================================================
    # SENKRONİZASYON (Sync Remote + açılış popup'ı)
    # =====================================================
    def _sync_status_guncelle(self):
        """Header'daki senkronizasyon durum etiketini güncelle."""
        try:
            st = sync.get_sync_status()
        except Exception:
            return
        last = st.get("last_sync_at") or "henüz yok"
        pend = st.get("pending", 0)
        txt = f"Son senkron: {last}  •  Bekleyen: {pend}"
        if st.get("conflicts"):
            txt += f"  •  Çakışma: {st['conflicts']}"
        try:
            self.sync_status_label.configure(text=txt)
        except Exception:
            pass

    def _sync_calistir_thread(self, on_done):
        """sync_now()'ı arka plan thread'inde çalıştır; sonucu ana thread'e taşı."""
        def worker():
            result = sync.sync_now()
            try:
                self.root.after(0, lambda: on_done(result))
            except Exception:
                pass
        threading.Thread(target=worker, daemon=True).start()

    def _sync_remote_clicked(self):
        """Sync Remote butonu: elle çift yönlü senkronizasyon."""
        if sync.is_running():
            messagebox.showinfo("Senkronizasyon", "Zaten bir senkronizasyon çalışıyor.")
            return
        self.sync_button.configure(text="⏳ Syncing...", state="disabled")

        def done(result):
            self.sync_button.configure(text="🔄 Sync Remote", state="normal")
            self._sync_status_guncelle()
            if result.skipped:
                return
            if result.offline:
                messagebox.showwarning("Senkronizasyon", result.summary())
            elif result.ok:
                messagebox.showinfo("Senkronizasyon", result.summary())
            else:
                messagebox.showerror("Senkronizasyon", result.summary())

        self._sync_calistir_thread(done)

    def _popup_kapat_butonlari(self, parent, popup, retry=False):
        for w in parent.winfo_children():
            w.destroy()
        if retry:
            ttkb.Button(
                parent, text="🔄 Tekrar Dene", bootstyle="success",
                command=lambda: (popup.destroy(), self._sync_remote_clicked()),
            ).pack(side=LEFT, padx=5)
        ttkb.Button(parent, text="Kapat", bootstyle="secondary",
                    command=popup.destroy).pack(side=LEFT, padx=5)

    def _baslangic_senkronizasyonu(self):
        """Açılışta otomatik senkronizasyon + görünür durum popup'ı."""
        popup = tk.Toplevel(self.root)
        popup.title("Senkronizasyon")
        popup.resizable(False, False)
        popup.transient(self.root)

        w, h = 470, 210
        popup.geometry(f"{w}x{h}")
        popup.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - w) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - h) // 3
        popup.geometry(f"+{x}+{y}")

        frame = ttkb.Frame(popup, padding=20)
        frame.pack(fill=BOTH, expand=True)

        ttkb.Label(frame, text="🔄 Senkronizasyon",
                   font=("Segoe UI", 13, "bold"), bootstyle="primary").pack(anchor=W)
        msg = ttkb.Label(
            frame,
            text="Uzak veritabanı ile senkronizasyon yapılıyor. Lütfen bekleyin...",
            font=("Segoe UI", 10), wraplength=430, justify=LEFT,
        )
        msg.pack(anchor=W, pady=(10, 8))

        pb = ttkb.Progressbar(frame, mode="indeterminate", bootstyle="info")
        pb.pack(fill=X, pady=(0, 10))
        pb.start(12)

        btnframe = ttkb.Frame(frame)
        btnframe.pack(fill=X, pady=(4, 0))

        self.sync_button.configure(text="⏳ Syncing...", state="disabled")

        def done(result):
            try:
                pb.stop()
            except Exception:
                pass
            self.sync_button.configure(text="🔄 Sync Remote", state="normal")
            self._sync_status_guncelle()

            if result.skipped:
                msg.configure(text=result.summary())
                popup.after(1500, popup.destroy)
                return
            if result.ok:
                msg.configure(text=result.summary())
                popup.after(2000, popup.destroy)
                return
            if result.offline:
                msg.configure(
                    text=result.summary() +
                    "\n\nYerel kayıt işlemleriniz normal şekilde çalışmaya devam ediyor.")
            else:
                msg.configure(text=result.summary())
            self._popup_kapat_butonlari(btnframe, popup, retry=True)

        self._sync_calistir_thread(done)

    # =====================================================
    # SEKME 1: VERİ GİRİŞİ
    # =====================================================
    def _build_veri_girisi_tab(self):
        """Veri girişi sekmesi."""
        tab = ttkb.Frame(self.notebook, padding=20)
        self.notebook.add(tab, text="  📝 Veri Girişi  ")

        # Sol panel - Form
        form_frame = ttkb.Labelframe(tab, text="Soru Çözüm Kaydı", padding=20, bootstyle="primary")
        form_frame.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 10))

        # Tarih seçimi
        ttkb.Label(form_frame, text="📅 Tarih:", font=("Segoe UI", 11)).grid(
            row=0, column=0, sticky=W, pady=8
        )

        tarih_frame = ttkb.Frame(form_frame)
        tarih_frame.grid(row=0, column=1, sticky=EW, pady=8, padx=(10, 0))

        # Tarih dropdown - son 30 gün
        self.tarih_listesi = []
        bugun = date.today()
        for i in range(30):
            gun = bugun - timedelta(days=i)
            if i == 0:
                label = f"Bugün ({gun.strftime('%d.%m.%Y')})"
            elif i == 1:
                label = f"Dün ({gun.strftime('%d.%m.%Y')})"
            else:
                label = gun.strftime("%d.%m.%Y")
            self.tarih_listesi.append((label, gun.strftime("%Y-%m-%d")))

        self.tarih_var = tk.StringVar(value=self.tarih_listesi[0][0])
        tarih_combo = ttkb.Combobox(
            tarih_frame,
            textvariable=self.tarih_var,
            values=[t[0] for t in self.tarih_listesi],
            state="readonly",
            font=("Segoe UI", 11),
            width=30,
        )
        tarih_combo.grid(row=0, column=0, sticky=EW)
        tarih_frame.columnconfigure(0, weight=1)

        # Ders seçimi
        ttkb.Label(form_frame, text="📖 Ders:", font=("Segoe UI", 11)).grid(
            row=1, column=0, sticky=W, pady=8
        )
        self.ders_var = tk.StringVar(value=DERSLER[0])
        ders_combo = ttkb.Combobox(
            form_frame,
            textvariable=self.ders_var,
            values=DERSLER,
            state="readonly",
            font=("Segoe UI", 11),
            width=30,
        )
        ders_combo.grid(row=1, column=1, sticky=EW, pady=8, padx=(10, 0))

        # Ders renk göstergesi
        self.ders_renk_label = ttkb.Label(form_frame, text="  ●  ", font=("Segoe UI", 16))
        self.ders_renk_label.grid(row=1, column=2, padx=5)
        self._update_ders_renk()
        ders_combo.bind("<<ComboboxSelected>>", lambda e: self._update_ders_renk())

        # Soru sayısı
        ttkb.Label(form_frame, text="📊 Çözülen Soru:", font=("Segoe UI", 11)).grid(
            row=2, column=0, sticky=W, pady=8
        )
        self.soru_var = tk.StringVar(value="0")
        soru_spin = ttkb.Spinbox(
            form_frame,
            from_=0,
            to=500,
            textvariable=self.soru_var,
            font=("Segoe UI", 11),
            width=10,
            bootstyle="primary",
        )
        soru_spin.grid(row=2, column=1, sticky=W, pady=8, padx=(10, 0))

        # Doğru sayısı
        ttkb.Label(form_frame, text="✅ Doğru:", font=("Segoe UI", 11)).grid(
            row=3, column=0, sticky=W, pady=8
        )
        self.dogru_var = tk.StringVar(value="0")
        dogru_spin = ttkb.Spinbox(
            form_frame,
            from_=0,
            to=500,
            textvariable=self.dogru_var,
            font=("Segoe UI", 11),
            width=10,
            bootstyle="success",
        )
        dogru_spin.grid(row=3, column=1, sticky=W, pady=8, padx=(10, 0))

        # Yanlış sayısı
        ttkb.Label(form_frame, text="❌ Yanlış:", font=("Segoe UI", 11)).grid(
            row=4, column=0, sticky=W, pady=8
        )
        self.yanlis_var = tk.StringVar(value="0")
        yanlis_spin = ttkb.Spinbox(
            form_frame,
            from_=0,
            to=500,
            textvariable=self.yanlis_var,
            font=("Segoe UI", 11),
            width=10,
            bootstyle="danger",
        )
        yanlis_spin.grid(row=4, column=1, sticky=W, pady=8, padx=(10, 0))

        # Boş sayısı (otomatik hesaplanır)
        ttkb.Label(form_frame, text="⬜ Boş:", font=("Segoe UI", 11)).grid(
            row=5, column=0, sticky=W, pady=8
        )
        self.bos_label = ttkb.Label(form_frame, text="0", font=("Segoe UI", 11, "bold"))
        self.bos_label.grid(row=5, column=1, sticky=W, pady=8, padx=(10, 0))

        # Net (otomatik hesaplanır)
        ttkb.Label(form_frame, text="🎯 Net:", font=("Segoe UI", 11)).grid(
            row=6, column=0, sticky=W, pady=8
        )
        self.net_label = ttkb.Label(
            form_frame, text="0.00", font=("Segoe UI", 14, "bold"), bootstyle="success"
        )
        self.net_label.grid(row=6, column=1, sticky=W, pady=8, padx=(10, 0))

        # Otomatik hesaplama bağlantıları
        self.soru_var.trace_add("write", self._hesapla_net)
        self.dogru_var.trace_add("write", self._hesapla_net)
        self.yanlis_var.trace_add("write", self._hesapla_net)

        # Kaydet butonu
        btn_frame = ttkb.Frame(form_frame)
        btn_frame.grid(row=7, column=0, columnspan=3, pady=20)

        ttkb.Button(
            btn_frame,
            text="💾 Kaydet",
            command=self._kaydet,
            bootstyle="success",
            width=20,
        ).pack(side=LEFT, padx=5)

        ttkb.Button(
            btn_frame,
            text="🔄 Temizle",
            command=self._formu_temizle,
            bootstyle="secondary-outline",
            width=15,
        ).pack(side=LEFT, padx=5)

        form_frame.columnconfigure(1, weight=1)

        # Sağ panel - Son girişler
        right_frame = ttkb.Labelframe(tab, text="Son Girişler (Bugün)", padding=10, bootstyle="info")
        right_frame.pack(side=RIGHT, fill=BOTH, expand=True)

        self.son_girisler_tree = ttkb.Treeview(
            right_frame,
            columns=("ders", "soru", "dogru", "yanlis", "net"),
            show="headings",
            height=15,
            bootstyle="info",
        )
        self.son_girisler_tree.heading("ders", text="Ders")
        self.son_girisler_tree.heading("soru", text="Soru")
        self.son_girisler_tree.heading("dogru", text="Doğru")
        self.son_girisler_tree.heading("yanlis", text="Yanlış")
        self.son_girisler_tree.heading("net", text="Net")

        self.son_girisler_tree.column("ders", width=100)
        self.son_girisler_tree.column("soru", width=60, anchor=CENTER)
        self.son_girisler_tree.column("dogru", width=60, anchor=CENTER)
        self.son_girisler_tree.column("yanlis", width=60, anchor=CENTER)
        self.son_girisler_tree.column("net", width=60, anchor=CENTER)

        scrollbar = ttkb.Scrollbar(right_frame, orient=VERTICAL, command=self.son_girisler_tree.yview)
        self.son_girisler_tree.configure(yscrollcommand=scrollbar.set)

        self.son_girisler_tree.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)

        # Bugünün özeti
        self._son_girisler_guncelle()

    def _update_ders_renk(self):
        """Ders renk göstergesini güncelle."""
        ders = self.ders_var.get()
        renk = DERS_RENKLERI.get(ders, "#000000")
        self.ders_renk_label.configure(foreground=renk)

    def _hesapla_net(self, *args):
        """Net ve boş hesapla."""
        try:
            soru = int(self.soru_var.get() or 0)
            dogru = int(self.dogru_var.get() or 0)
            yanlis = int(self.yanlis_var.get() or 0)
            bos = max(0, soru - dogru - yanlis)
            net = dogru - (yanlis / 4.0)

            self.bos_label.configure(text=str(bos))
            self.net_label.configure(text=f"{net:.2f}")
        except ValueError:
            pass

    def _kaydet(self):
        """Kayıt ekle."""
        try:
            # Tarih al
            tarih_label = self.tarih_var.get()
            tarih = None
            for label, val in self.tarih_listesi:
                if label == tarih_label:
                    tarih = val
                    break
            if not tarih:
                Messagebox.show_error("Lütfen bir tarih seçin!", "Hata")
                return

            ders = self.ders_var.get()
            soru = int(self.soru_var.get() or 0)
            dogru = int(self.dogru_var.get() or 0)
            yanlis = int(self.yanlis_var.get() or 0)

            # Doğrulama
            if soru <= 0:
                Messagebox.show_error("Soru sayısı 0'dan büyük olmalıdır!", "Hata")
                return
            if dogru + yanlis > soru:
                Messagebox.show_error("Doğru + Yanlış, soru sayısından fazla olamaz!", "Hata")
                return

            db.kayit_ekle(tarih, ders, soru, dogru, yanlis)
            Messagebox.show_info(
                f"✅ Kayıt başarıyla eklendi!\n\n"
                f"Tarih: {tarih_label}\n"
                f"Ders: {ders}\n"
                f"Soru: {soru} | Doğru: {dogru} | Yanlış: {yanlis}",
                "Başarılı",
            )
            self._formu_temizle()
            self._son_girisler_guncelle()

        except ValueError:
            Messagebox.show_error("Lütfen geçerli sayılar girin!", "Hata")

    def _formu_temizle(self):
        """Formu temizle."""
        self.soru_var.set("0")
        self.dogru_var.set("0")
        self.yanlis_var.set("0")

    def _son_girisler_guncelle(self):
        """Bugünün girişlerini güncelle."""
        for item in self.son_girisler_tree.get_children():
            self.son_girisler_tree.delete(item)

        bugun = date.today().strftime("%Y-%m-%d")
        kayitlar = db.tum_kayitlari_getir(tarih_baslangic=bugun, tarih_bitis=bugun)

        for k in kayitlar:
            self.son_girisler_tree.insert(
                "",
                END,
                values=(k["ders"], k["soru_sayisi"], k["dogru"], k["yanlis"], k["net"]),
            )

    # =====================================================
    # SEKME 2: TABLO GÖRÜNÜMÜ
    # =====================================================
    def _build_tablo_tab(self):
        """Tablo görünümü sekmesi."""
        tab = ttkb.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="  📋 Tablo Görünümü  ")

        # Filtre alanı
        filter_frame = ttkb.Labelframe(tab, text="Filtreler", padding=10, bootstyle="secondary")
        filter_frame.pack(fill=X, pady=(0, 10))

        # Başlangıç tarihi
        ttkb.Label(filter_frame, text="Başlangıç:", font=("Segoe UI", 10)).pack(side=LEFT, padx=5)
        self.tablo_baslangic_var = tk.StringVar(
            value=(date.today() - timedelta(days=30)).strftime("%Y-%m-%d")
        )
        ttkb.Entry(
            filter_frame, textvariable=self.tablo_baslangic_var, width=12, font=("Segoe UI", 10)
        ).pack(side=LEFT, padx=5)

        # Bitiş tarihi
        ttkb.Label(filter_frame, text="Bitiş:", font=("Segoe UI", 10)).pack(side=LEFT, padx=5)
        self.tablo_bitis_var = tk.StringVar(value=date.today().strftime("%Y-%m-%d"))
        ttkb.Entry(
            filter_frame, textvariable=self.tablo_bitis_var, width=12, font=("Segoe UI", 10)
        ).pack(side=LEFT, padx=5)

        # Ders filtresi
        ttkb.Label(filter_frame, text="Ders:", font=("Segoe UI", 10)).pack(side=LEFT, padx=5)
        self.tablo_ders_var = tk.StringVar(value="Tümü")
        ttkb.Combobox(
            filter_frame,
            textvariable=self.tablo_ders_var,
            values=["Tümü"] + DERSLER,
            state="readonly",
            width=12,
            font=("Segoe UI", 10),
        ).pack(side=LEFT, padx=5)

        # Filtrele butonu
        ttkb.Button(
            filter_frame,
            text="🔍 Filtrele",
            command=self._tablo_filtrele,
            bootstyle="primary",
        ).pack(side=LEFT, padx=10)

        # Sil butonu
        ttkb.Button(
            filter_frame,
            text="🗑️ Seçili Sil",
            command=self._secili_kayit_sil,
            bootstyle="danger-outline",
        ).pack(side=RIGHT, padx=5)

        # Tablo
        tablo_frame = ttkb.Frame(tab)
        tablo_frame.pack(fill=BOTH, expand=True)

        columns = ("id", "tarih", "ders", "soru", "dogru", "yanlis", "net", "olusturma")
        self.ana_tablo = ttkb.Treeview(
            tablo_frame,
            columns=columns,
            show="headings",
            selectmode="extended",
            bootstyle="primary",
        )

        headers = {
            "id": ("ID", 50),
            "tarih": ("Tarih", 100),
            "ders": ("Ders", 100),
            "soru": ("Soru", 70),
            "dogru": ("Doğru", 70),
            "yanlis": ("Yanlış", 70),
            "net": ("Net", 80),
            "olusturma": ("Kayıt Zamanı", 150),
        }

        for col, (header, width) in headers.items():
            self.ana_tablo.heading(col, text=header)
            anchor = CENTER if col not in ("ders", "olusturma") else W
            self.ana_tablo.column(col, width=width, anchor=anchor)

        scrollbar_y = ttkb.Scrollbar(tablo_frame, orient=VERTICAL, command=self.ana_tablo.yview)
        scrollbar_x = ttkb.Scrollbar(tablo_frame, orient=HORIZONTAL, command=self.ana_tablo.xview)
        self.ana_tablo.configure(yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set)

        self.ana_tablo.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar_y.pack(side=RIGHT, fill=Y)

        # Özet bilgi
        self.tablo_ozet_label = ttkb.Label(
            tab, text="", font=("Segoe UI", 10), bootstyle="info"
        )
        self.tablo_ozet_label.pack(fill=X, pady=5)

        # Sekme açıldığında tabloyu güncelle
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    def _tablo_filtrele(self):
        """Tabloyu filtrele."""
        for item in self.ana_tablo.get_children():
            self.ana_tablo.delete(item)

        baslangic = self.tablo_baslangic_var.get()
        bitis = self.tablo_bitis_var.get()
        ders = self.tablo_ders_var.get()

        kayitlar = db.tum_kayitlari_getir(baslangic, bitis, ders)

        toplam_soru = 0
        toplam_dogru = 0
        toplam_yanlis = 0

        for k in kayitlar:
            tarih_formatted = datetime.strptime(k["tarih"], "%Y-%m-%d").strftime("%d.%m.%Y")
            self.ana_tablo.insert(
                "",
                END,
                values=(
                    k["id"],
                    tarih_formatted,
                    k["ders"],
                    k["soru_sayisi"],
                    k["dogru"],
                    k["yanlis"],
                    k["net"],
                    k["created_at"],
                ),
            )
            toplam_soru += k["soru_sayisi"]
            toplam_dogru += k["dogru"]
            toplam_yanlis += k["yanlis"]

        self.tablo_ozet_label.configure(
            text=f"📊 Toplam: {len(kayitlar)} kayıt | "
            f"Soru: {toplam_soru} | Doğru: {toplam_dogru} | Yanlış: {toplam_yanlis} | "
            f"Net: {toplam_dogru - toplam_yanlis / 4:.2f}"
        )

    def _secili_kayit_sil(self):
        """Seçili kayıtları sil (çoklu seçim destekli)."""
        selected = self.ana_tablo.selection()
        if not selected:
            Messagebox.show_warning("Lütfen silmek istediğiniz kayıtları seçin!\n\n"
                "İpucu: Ctrl+tıklama ile birden fazla,\n"
                "Shift+tıklama ile aralık seçebilirsiniz.", "Uyarı")
            return

        adet = len(selected)
        confirm = Messagebox.yesno(
            f"{adet} kayıt silinecek. Emin misiniz?", "Onay")
        if confirm == "Yes":
            for item in selected:
                values = self.ana_tablo.item(item, "values")
                kayit_id = int(values[0])
                db.kayit_sil(kayit_id)

            self._tablo_filtrele()
            self._son_girisler_guncelle()
            Messagebox.show_info(f"{adet} kayıt silindi!", "Başarılı")

    def _on_tab_changed(self, event):
        """Sekme değiştiğinde verileri güncelle."""
        tab_index = self.notebook.index(self.notebook.select())
        if tab_index == 1:
            self._tablo_filtrele()
        elif tab_index == 2:
            self._grafikleri_guncelle()
        elif tab_index == 3:
            self._trend_guncelle()
        elif tab_index == 4:
            self._sinav_listesini_guncelle()

    # =====================================================
    # VERİ DIŞA / İÇE AKTARMA
    # =====================================================
    def _export_data(self):
        """Tüm verileri JSON dosyasına dışa aktar."""
        default_name = f"lgs_yedek_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        dosya_yolu = filedialog.asksaveasfilename(
            title="Verileri Dışa Aktar",
            defaultextension=".json",
            initialfile=default_name,
            filetypes=[("JSON Dosyası", "*.json"), ("Tüm Dosyalar", "*.*")],
        )
        if not dosya_yolu:
            return

        try:
            stats = db.export_data(dosya_yolu)
            msg = (
                f"Veriler başarıyla dışa aktarıldı!\n\n"
                f"📁 Dosya: {dosya_yolu}\n\n"
                f"📊 İstatistikler:\n"
                f"  • Günlük soru kayıtları: {stats['soru_takip']}\n"
                f"  • Kurumlar: {stats['kurumlar']}\n"
                f"  • Sınavlar: {stats['sinavlar']}\n"
                f"  • Sınav ders detayları: {stats['sinav_dersleri']}"
            )
            Messagebox.show_info(msg, "Dışa Aktarma Başarılı")
        except Exception as e:
            Messagebox.show_error(f"Dışa aktarma hatası:\n{str(e)}", "Hata")

    def _import_data(self):
        """JSON dosyasından veri içe aktar."""
        dosya_yolu = filedialog.askopenfilename(
            title="Verileri İçe Aktar",
            filetypes=[("JSON Dosyası", "*.json"), ("Tüm Dosyalar", "*.*")],
        )
        if not dosya_yolu:
            return

        # Mod seçimi
        result = Messagebox.yesnocancel(
            "İçe aktarma modu seçin:\n\n"
            "• EVET → Sıfırla & İçe Aktar (mevcut veriler SİLİNİR, yedeğin yüklenir)\n"
            "• HAYIR → Ekle (mevcut verilerin üzerine eklenir)\n"
            "• İPTAL → Vazgeç",
            "İçe Aktarma Modu",
        )

        if result == "Cancel" or result is None:
            return

        mod = "sifirla" if result == "Yes" else "ekle"
        mod_str = "Sıfırla & İçe Aktar" if mod == "sifirla" else "Mevcut Verilere Ekle"

        if mod == "sifirla":
            confirm = Messagebox.yesno(
                "⚠️ DİKKAT!\n\n"
                "Mevcut TÜM verileriniz silinecek ve yedek dosyası yüklenecek.\n\n"
                "Devam etmek istiyor musunuz?",
                "Son Onay"
            )
            if confirm != "Yes":
                return

        try:
            stats = db.import_data(dosya_yolu, mod=mod)
            msg = (
                f"Veriler başarıyla içe aktarıldı!\n\n"
                f"📋 Mod: {mod_str}\n\n"
                f"📊 Eklenen kayıtlar:\n"
                f"  • Günlük soru kayıtları: {stats['soru_takip']}\n"
                f"  • Kurumlar: {stats['kurumlar']}\n"
                f"  • Sınavlar: {stats['sinavlar']}\n"
                f"  • Sınav ders detayları: {stats['sinav_dersleri']}"
            )
            Messagebox.show_info(msg, "İçe Aktarma Başarılı")

            # Görünümleri yenile
            self._son_girisler_guncelle()
            tab_index = self.notebook.index(self.notebook.select())
            if tab_index == 1:
                self._tablo_filtrele()
        except ValueError as e:
            Messagebox.show_error(str(e), "Sürüm Uyumsuzluğu")
        except Exception as e:
            Messagebox.show_error(f"İçe aktarma hatası:\n{str(e)}", "Hata")

    # =====================================================
    # SEKME 3: GRAFİKLER
    # =====================================================
    def _build_grafik_tab(self):
        """Grafik sekmesi."""
        tab = ttkb.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="  📊 Grafikler  ")

        # Filtre alanı
        filter_frame = ttkb.Labelframe(tab, text="Grafik Filtreleri", padding=10, bootstyle="secondary")
        filter_frame.pack(fill=X, pady=(0, 10))

        # Dönem seçimi
        ttkb.Label(filter_frame, text="Dönem:", font=("Segoe UI", 10)).pack(side=LEFT, padx=5)
        self.grafik_donem_var = tk.StringVar(value="Son 30 Gün")
        ttkb.Combobox(
            filter_frame,
            textvariable=self.grafik_donem_var,
            values=["Son 7 Gün", "Son 14 Gün", "Son 30 Gün", "Son 60 Gün", "Son 90 Gün", "Tüm Zamanlar"],
            state="readonly",
            width=15,
            font=("Segoe UI", 10),
        ).pack(side=LEFT, padx=5)

        # Grafik tipi
        ttkb.Label(filter_frame, text="Grafik:", font=("Segoe UI", 10)).pack(side=LEFT, padx=5)
        self.grafik_tip_var = tk.StringVar(value="Günlük Soru (Line)")
        ttkb.Combobox(
            filter_frame,
            textvariable=self.grafik_tip_var,
            values=[
                "Günlük Soru (Line)",
                "Günlük Net (Line)",
                "Ders Dağılımı (Pie)",
                "Ders Karşılaştırma (Bar)",
                "Doğru/Yanlış Oranı (Bar)",
                "Aylık Özet (Bar)",
            ],
            state="readonly",
            width=25,
            font=("Segoe UI", 10),
        ).pack(side=LEFT, padx=5)

        ttkb.Button(
            filter_frame,
            text="📊 Göster",
            command=self._grafikleri_guncelle,
            bootstyle="success",
        ).pack(side=LEFT, padx=10)

        # Grafik alanı
        self.grafik_frame = ttkb.Frame(tab)
        self.grafik_frame.pack(fill=BOTH, expand=True)

        # Renk göstergesi
        legend_frame = ttkb.Frame(tab)
        legend_frame.pack(fill=X, pady=5)
        for ders, renk in DERS_RENKLERI.items():
            lf = ttkb.Frame(legend_frame)
            lf.pack(side=LEFT, padx=10)
            canvas = tk.Canvas(lf, width=15, height=15, highlightthickness=0)
            canvas.create_rectangle(0, 0, 15, 15, fill=renk, outline=renk)
            canvas.pack(side=LEFT, padx=(0, 3))
            ttkb.Label(lf, text=ders, font=("Segoe UI", 9)).pack(side=LEFT)

    def _get_donem_tarihleri(self):
        """Dönem filtresi tarihlerini hesapla."""
        donem = self.grafik_donem_var.get()
        bitis = date.today()
        gun_map = {
            "Son 7 Gün": 7,
            "Son 14 Gün": 14,
            "Son 30 Gün": 30,
            "Son 60 Gün": 60,
            "Son 90 Gün": 90,
        }
        if donem in gun_map:
            baslangic = bitis - timedelta(days=gun_map[donem])
        else:
            baslangic = date(2024, 1, 1)

        return baslangic.strftime("%Y-%m-%d"), bitis.strftime("%Y-%m-%d")

    def _grafikleri_guncelle(self):
        """Grafikleri güncelle."""
        # Eski grafiği temizle
        for widget in self.grafik_frame.winfo_children():
            widget.destroy()

        tip = self.grafik_tip_var.get()
        baslangic, bitis = self._get_donem_tarihleri()

        fig = Figure(figsize=(10, 5), dpi=100)
        fig.patch.set_facecolor("#f8f9fa")

        if tip == "Günlük Soru (Line)":
            self._ciz_gunluk_line(fig, baslangic, bitis, deger="toplam_soru", baslik="Günlük Çözülen Soru Sayısı")
        elif tip == "Günlük Net (Line)":
            self._ciz_gunluk_line(fig, baslangic, bitis, deger="toplam_net", baslik="Günlük Net Sayısı")
        elif tip == "Ders Dağılımı (Pie)":
            self._ciz_pie(fig, baslangic, bitis)
        elif tip == "Ders Karşılaştırma (Bar)":
            self._ciz_ders_bar(fig, baslangic, bitis)
        elif tip == "Doğru/Yanlış Oranı (Bar)":
            self._ciz_dogru_yanlis_bar(fig, baslangic, bitis)
        elif tip == "Aylık Özet (Bar)":
            self._ciz_aylik_bar(fig)

        canvas = FigureCanvasTkAgg(fig, master=self.grafik_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=BOTH, expand=True)

        toolbar = NavigationToolbar2Tk(canvas, self.grafik_frame)
        toolbar.update()

    def _ciz_gunluk_line(self, fig, baslangic, bitis, deger="toplam_soru", baslik=""):
        """Günlük line chart çiz."""
        veriler = db.gunluk_ozet(baslangic, bitis)
        if not veriler:
            ax = fig.add_subplot(111)
            ax.text(0.5, 0.5, "Veri bulunamadı", ha="center", va="center", fontsize=14)
            return

        df = pd.DataFrame(veriler)
        df["tarih"] = pd.to_datetime(df["tarih"])

        ax = fig.add_subplot(111)
        ax.set_facecolor("#ffffff")

        # Toplam gün sayısına göre annotation sıklığı ayarla
        toplam_gun = df["tarih"].nunique()
        if toplam_gun <= 7:
            her_n = 1
        elif toplam_gun <= 14:
            her_n = 2
        elif toplam_gun <= 30:
            her_n = 4
        else:
            her_n = 7

        for ders in DERSLER:
            ders_df = df[df["ders"] == ders].sort_values("tarih").reset_index(drop=True)
            if not ders_df.empty:
                ax.plot(
                    ders_df["tarih"],
                    ders_df[deger],
                    marker="o",
                    label=ders,
                    color=DERS_RENKLERI[ders],
                    linewidth=2,
                    markersize=5,
                )
                # Noktalara değer yaz
                for idx, row in ders_df.iterrows():
                    if idx % her_n == 0:
                        val = row[deger]
                        val_str = f"{val:.1f}" if isinstance(val, float) else str(int(val))
                        ax.annotate(
                            val_str,
                            (row["tarih"], val),
                            textcoords="offset points",
                            xytext=(0, 8),
                            ha="center",
                            fontsize=7,
                            fontweight="bold",
                            color=DERS_RENKLERI[ders],
                        )

        ax.set_title(baslik, fontsize=14, fontweight="bold", pad=10)
        ax.set_xlabel("Tarih", fontsize=10)
        ax.set_ylabel("Sayı", fontsize=10)
        ax.legend(loc="upper left", fontsize=9)
        ax.grid(True, alpha=0.3)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        fig.autofmt_xdate()
        fig.tight_layout()

    def _ciz_pie(self, fig, baslangic, bitis):
        """Ders dağılımı pie chart."""
        veriler = db.ders_bazinda_toplam(baslangic, bitis)
        if not veriler:
            ax = fig.add_subplot(111)
            ax.text(0.5, 0.5, "Veri bulunamadı", ha="center", va="center", fontsize=14)
            return

        ax = fig.add_subplot(121)
        labels = [v["ders"] for v in veriler]
        sizes = [v["toplam_soru"] for v in veriler]
        colors = [DERS_RENKLERI.get(v["ders"], "#999") for v in veriler]

        wedges, texts, autotexts = ax.pie(
            sizes,
            labels=labels,
            autopct="%1.1f%%",
            colors=colors,
            startangle=90,
            textprops={"fontsize": 10},
        )
        ax.set_title("Toplam Soru Dağılımı", fontsize=13, fontweight="bold")

        # Net dağılımı
        ax2 = fig.add_subplot(122)
        net_sizes = [max(0, v["toplam_net"]) for v in veriler]
        if sum(net_sizes) > 0:
            wedges2, texts2, autotexts2 = ax2.pie(
                net_sizes,
                labels=labels,
                autopct="%1.1f%%",
                colors=colors,
                startangle=90,
                textprops={"fontsize": 10},
            )
        ax2.set_title("Net Dağılımı", fontsize=13, fontweight="bold")
        fig.tight_layout()

    def _ciz_ders_bar(self, fig, baslangic, bitis):
        """Ders karşılaştırma bar chart."""
        veriler = db.ders_bazinda_toplam(baslangic, bitis)
        if not veriler:
            ax = fig.add_subplot(111)
            ax.text(0.5, 0.5, "Veri bulunamadı", ha="center", va="center", fontsize=14)
            return

        ax = fig.add_subplot(111)
        dersler = [v["ders"] for v in veriler]
        sorular = [v["toplam_soru"] for v in veriler]
        renkler = [DERS_RENKLERI.get(d, "#999") for d in dersler]

        netler = [v["toplam_net"] for v in veriler]

        bars = ax.bar(dersler, sorular, color=renkler, edgecolor="white", linewidth=1.5)

        # Soru sayısı ve net değerlerini barların üstüne yaz
        for bar, soru_val, net_val in zip(bars, sorular, netler):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.5,
                f"{soru_val} soru\n{net_val:.1f} net",
                ha="center",
                va="bottom",
                fontweight="bold",
                fontsize=9,
            )

        ax.set_title("Ders Bazında Toplam Soru & Net", fontsize=14, fontweight="bold")
        ax.set_ylabel("Soru Sayısı", fontsize=11)
        ax.grid(True, axis="y", alpha=0.3)
        fig.tight_layout()

    def _ciz_dogru_yanlis_bar(self, fig, baslangic, bitis):
        """Doğru/Yanlış oranı bar chart."""
        veriler = db.ders_bazinda_toplam(baslangic, bitis)
        if not veriler:
            ax = fig.add_subplot(111)
            ax.text(0.5, 0.5, "Veri bulunamadı", ha="center", va="center", fontsize=14)
            return

        ax = fig.add_subplot(111)
        dersler = [v["ders"] for v in veriler]
        dogrular = [v["toplam_dogru"] for v in veriler]
        yanlislar = [v["toplam_yanlis"] for v in veriler]

        x = np.arange(len(dersler))
        width = 0.35

        bars1 = ax.bar(x - width / 2, dogrular, width, label="Doğru", color="#2ECC71", edgecolor="white")
        bars2 = ax.bar(x + width / 2, yanlislar, width, label="Yanlış", color="#E74C3C", edgecolor="white")

        netler = [v["toplam_net"] for v in veriler]
        for bar, val, net_val in zip(bars1, dogrular, netler):
            if val > 0:
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
                        f"{val}", ha="center", fontweight="bold", fontsize=10, color="#27ae60")
        for bar, val in zip(bars2, yanlislar):
            if val > 0:
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
                        f"{val}", ha="center", fontweight="bold", fontsize=10, color="#c0392b")
        # Net değerlerini x ekseninin altına yaz
        for i, (ders_adi, net_val) in enumerate(zip(dersler, netler)):
            ax.text(i, -0.08, f"Net: {net_val:.1f}", ha="center", fontsize=9,
                    fontweight="bold", color="#2c3e50", transform=ax.get_xaxis_transform())

        ax.set_title("Doğru / Yanlış Karşılaştırması", fontsize=14, fontweight="bold")
        ax.set_xticks(x)
        ax.set_xticklabels(dersler)
        ax.legend(fontsize=11)
        ax.grid(True, axis="y", alpha=0.3)
        fig.tight_layout()

    def _ciz_aylik_bar(self, fig):
        """Aylık özet bar chart."""
        veriler = db.aylik_ozet()
        if not veriler:
            ax = fig.add_subplot(111)
            ax.text(0.5, 0.5, "Veri bulunamadı", ha="center", va="center", fontsize=14)
            return

        df = pd.DataFrame(veriler)
        aylar = sorted(df["ay"].unique())

        ax = fig.add_subplot(111)
        x = np.arange(len(aylar))
        bar_width = 0.12

        for i, ders in enumerate(DERSLER):
            ders_df = df[df["ders"] == ders]
            values = []
            for ay in aylar:
                ay_data = ders_df[ders_df["ay"] == ay]
                values.append(ay_data["toplam_soru"].sum() if not ay_data.empty else 0)

            rects = ax.bar(
                x + i * bar_width,
                values,
                bar_width,
                label=ders,
                color=DERS_RENKLERI[ders],
            )
            # Barların üstüne değer yaz
            for rect, v in zip(rects, values):
                if v > 0:
                    ax.text(
                        rect.get_x() + rect.get_width() / 2,
                        rect.get_height() + 0.3,
                        str(int(v)),
                        ha="center", va="bottom",
                        fontsize=7, fontweight="bold",
                    )

        # Ay etiketlerini düzenle
        ay_labels = []
        for ay in aylar:
            yil, ay_no = ay.split("-")
            ay_labels.append(f"{AY_ISIMLERI.get(int(ay_no), ay_no)} {yil}")

        ax.set_title("Aylık Soru Özeti", fontsize=14, fontweight="bold")
        ax.set_xticks(x + bar_width * 2.5)
        ax.set_xticklabels(ay_labels, rotation=30, ha="right")
        ax.legend(fontsize=9, loc="upper left")
        ax.grid(True, axis="y", alpha=0.3)
        fig.tight_layout()

    # =====================================================
    # SEKME 4: TREND ANALİZİ
    # =====================================================
    def _build_trend_tab(self):
        """Trend analizi sekmesi."""
        tab = ttkb.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="  📈 Trend Analizi  ")

        # Filtre alanı
        filter_frame = ttkb.Labelframe(tab, text="Trend Filtreleri", padding=10, bootstyle="secondary")
        filter_frame.pack(fill=X, pady=(0, 10))

        ttkb.Label(filter_frame, text="Son Gün:", font=("Segoe UI", 10)).pack(side=LEFT, padx=5)
        self.trend_gun_var = tk.StringVar(value="30")
        ttkb.Combobox(
            filter_frame,
            textvariable=self.trend_gun_var,
            values=["7", "14", "30", "60", "90", "180"],
            state="readonly",
            width=8,
            font=("Segoe UI", 10),
        ).pack(side=LEFT, padx=5)

        ttkb.Label(filter_frame, text="Ders:", font=("Segoe UI", 10)).pack(side=LEFT, padx=5)
        self.trend_ders_var = tk.StringVar(value="Tümü")
        ttkb.Combobox(
            filter_frame,
            textvariable=self.trend_ders_var,
            values=["Tümü"] + DERSLER,
            state="readonly",
            width=12,
            font=("Segoe UI", 10),
        ).pack(side=LEFT, padx=5)

        ttkb.Label(filter_frame, text="Metrik:", font=("Segoe UI", 10)).pack(side=LEFT, padx=5)
        self.trend_metrik_var = tk.StringVar(value="Soru Sayısı")
        ttkb.Combobox(
            filter_frame,
            textvariable=self.trend_metrik_var,
            values=["Soru Sayısı", "Net", "Doğru Sayısı", "Başarı Oranı (%)"],
            state="readonly",
            width=18,
            font=("Segoe UI", 10),
        ).pack(side=LEFT, padx=5)

        ttkb.Button(
            filter_frame,
            text="📈 Göster",
            command=self._trend_guncelle,
            bootstyle="success",
        ).pack(side=LEFT, padx=10)

        # İçerik: grafik üstte, analiz altta (PanedWindow ile)
        paned = ttkb.Panedwindow(tab, orient=tk.VERTICAL)
        paned.pack(fill=BOTH, expand=True)

        # Trend grafik alanı
        self.trend_grafik_frame = ttkb.Frame(paned)
        paned.add(self.trend_grafik_frame, weight=3)

        # Analiz paneli
        analiz_outer = ttkb.Labelframe(paned, text="🧠 Akıllı Analiz & Öneriler", padding=10, bootstyle="info")
        paned.add(analiz_outer, weight=2)

        self.analiz_text = tk.Text(
            analiz_outer,
            wrap=tk.WORD,
            font=("Segoe UI", 10),
            bg="#f8f9fa",
            fg="#2c3e50",
            relief=tk.FLAT,
            padx=10,
            pady=10,
            height=8,
        )
        analiz_scroll = ttkb.Scrollbar(analiz_outer, orient=VERTICAL, command=self.analiz_text.yview)
        self.analiz_text.configure(yscrollcommand=analiz_scroll.set)
        self.analiz_text.pack(side=LEFT, fill=BOTH, expand=True)
        analiz_scroll.pack(side=RIGHT, fill=Y)

        # Text widget tag'leri (renklendirme)
        self.analiz_text.tag_configure("baslik", font=("Segoe UI", 12, "bold"), foreground="#2c3e50")
        self.analiz_text.tag_configure("alt_baslik", font=("Segoe UI", 10, "bold"), foreground="#34495e")
        self.analiz_text.tag_configure("iyi", foreground="#27ae60", font=("Segoe UI", 10))
        self.analiz_text.tag_configure("kotu", foreground="#e74c3c", font=("Segoe UI", 10))
        self.analiz_text.tag_configure("uyari", foreground="#f39c12", font=("Segoe UI", 10, "bold"))
        self.analiz_text.tag_configure("bilgi", foreground="#3498db", font=("Segoe UI", 10))
        self.analiz_text.tag_configure("normal", font=("Segoe UI", 10))
        self.analiz_text.tag_configure("oneri", font=("Segoe UI", 10, "bold"), foreground="#8e44ad")
        for ders in DERSLER:
            self.analiz_text.tag_configure(f"renk_{ders}", foreground=DERS_RENKLERI[ders], font=("Segoe UI", 10, "bold"))

    def _trend_guncelle(self):
        """Trend grafiğini güncelle."""
        for widget in self.trend_grafik_frame.winfo_children():
            widget.destroy()

        son_gun = int(self.trend_gun_var.get())
        ders = self.trend_ders_var.get()
        metrik = self.trend_metrik_var.get()

        veriler = db.trend_verisi(ders if ders != "Tümü" else None, son_gun)

        if not veriler:
            lbl = ttkb.Label(
                self.trend_grafik_frame,
                text="📭 Seçilen kriterlere uygun veri bulunamadı.\nLütfen önce veri girişi yapın.",
                font=("Segoe UI", 14),
                bootstyle="secondary",
            )
            lbl.pack(expand=True)
            self._analiz_temizle()
            return

        df = pd.DataFrame(veriler)
        df["tarih"] = pd.to_datetime(df["tarih"])

        if metrik == "Başarı Oranı (%)":
            df["metrik"] = (df["toplam_dogru"] / df["toplam_soru"] * 100).fillna(0)
        elif metrik == "Net":
            df["metrik"] = df["toplam_net"]
        elif metrik == "Doğru Sayısı":
            df["metrik"] = df["toplam_dogru"]
        else:
            df["metrik"] = df["toplam_soru"]

        fig = Figure(figsize=(10, 4), dpi=100)
        fig.patch.set_facecolor("#f8f9fa")

        ax = fig.add_subplot(111)
        ax.set_facecolor("#ffffff")

        aktif_dersler = DERSLER if ders == "Tümü" else [ders]

        # Annotation sıklığı
        toplam_gun = df["tarih"].nunique()
        if toplam_gun <= 7:
            her_n = 1
        elif toplam_gun <= 14:
            her_n = 2
        elif toplam_gun <= 30:
            her_n = 3
        else:
            her_n = 5

        for d in aktif_dersler:
            ders_df = df[df["ders"] == d].sort_values("tarih").reset_index(drop=True)
            if ders_df.empty:
                continue

            renk = DERS_RENKLERI.get(d, "#999")

            # Ana veri çizgisi
            ax.plot(
                ders_df["tarih"],
                ders_df["metrik"],
                marker="o",
                label=d,
                color=renk,
                linewidth=2,
                markersize=5,
                alpha=0.7,
            )

            # Noktalara değer yaz
            for idx, row in ders_df.iterrows():
                if idx % her_n == 0:
                    val = row["metrik"]
                    val_str = f"{val:.1f}" if isinstance(val, float) else str(int(val))
                    ax.annotate(
                        val_str,
                        (row["tarih"], val),
                        textcoords="offset points",
                        xytext=(0, 8),
                        ha="center",
                        fontsize=7,
                        fontweight="bold",
                        color=renk,
                    )

            # Trend çizgisi (moving average)
            if len(ders_df) >= 3:
                window = min(7, len(ders_df))
                ders_df = ders_df.copy()
                ders_df["trend"] = ders_df["metrik"].rolling(window=window, min_periods=1).mean()
                ax.plot(
                    ders_df["tarih"],
                    ders_df["trend"],
                    linestyle="--",
                    color=renk,
                    linewidth=2.5,
                    alpha=0.9,
                    label=f"{d} (Trend)",
                )

        ax.set_title(
            f"📈 {metrik} Trend Analizi (Son {son_gun} Gün)",
            fontsize=14,
            fontweight="bold",
            pad=10,
        )
        ax.set_xlabel("Tarih", fontsize=11)
        ax.set_ylabel(metrik, fontsize=11)
        ax.legend(loc="best", fontsize=8, ncol=2)
        ax.grid(True, alpha=0.3)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        fig.autofmt_xdate()
        fig.tight_layout()

        canvas = FigureCanvasTkAgg(fig, master=self.trend_grafik_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=BOTH, expand=True)

        toolbar = NavigationToolbar2Tk(canvas, self.trend_grafik_frame)
        toolbar.update()

        # Akıllı analizi çalıştır
        self._analiz_yap(son_gun, ders)

    def _analiz_temizle(self):
        """Analiz panelini temizle."""
        self.analiz_text.configure(state=tk.NORMAL)
        self.analiz_text.delete("1.0", tk.END)
        self.analiz_text.insert(tk.END, "Analiz için veri bulunamadı.", "normal")
        self.analiz_text.configure(state=tk.DISABLED)

    def _analiz_yap(self, son_gun=30, secili_ders="Tümü"):
        """Trend verisini analiz edip öneri üret. Ders seçiliyse sadece o ders analiz edilir."""
        self.analiz_text.configure(state=tk.NORMAL)
        self.analiz_text.delete("1.0", tk.END)

        # Tüm veriler (tüm dersler için - karşılaştırma gerekebilir)
        veriler = db.trend_verisi(None, son_gun)
        if not veriler:
            self.analiz_text.insert(tk.END, "Analiz için yeterli veri yok.", "normal")
            self.analiz_text.configure(state=tk.DISABLED)
            return

        df = pd.DataFrame(veriler)
        df["tarih"] = pd.to_datetime(df["tarih"])
        df["basari"] = (df["toplam_dogru"] / df["toplam_soru"] * 100).fillna(0)

        # Karşılaştırma için son yarı / ilk yarı
        orta_tarih = df["tarih"].min() + (df["tarih"].max() - df["tarih"].min()) / 2

        tek_ders = secili_ders != "Tümü"
        hedef_dersler = [secili_ders] if tek_ders else DERSLER

        baslik_ders = secili_ders if tek_ders else "Tüm Dersler"
        self.analiz_text.insert(tk.END, f"📋 PERFORMANS ANALİZİ — {baslik_ders} (Son {son_gun} Gün)\n", "baslik")
        self.analiz_text.insert(tk.END, "═" * 60 + "\n\n", "normal")

        # ── Ders bazında analiz ──
        ders_analizleri = []
        for d in hedef_dersler:
            ders_df = df[df["ders"] == d].sort_values("tarih")
            if ders_df.empty:
                ders_analizleri.append({
                    "ders": d, "durum": "veri_yok",
                })
                continue

            toplam_soru = ders_df["toplam_soru"].sum()
            toplam_dogru = ders_df["toplam_dogru"].sum()
            toplam_yanlis = ders_df["toplam_yanlis"].sum()
            toplam_net = ders_df["toplam_net"].sum()
            ort_basari = (toplam_dogru / toplam_soru * 100) if toplam_soru > 0 else 0
            gun_sayisi = ders_df["tarih"].nunique()
            gunluk_ort_soru = toplam_soru / max(1, gun_sayisi)

            # Trend hesaplama: ilk yarı vs son yarı
            ilk_yari = ders_df[ders_df["tarih"] <= orta_tarih]
            son_yari = ders_df[ders_df["tarih"] > orta_tarih]

            if not ilk_yari.empty and not son_yari.empty:
                ilk_basari = ilk_yari["toplam_dogru"].sum() / max(1, ilk_yari["toplam_soru"].sum()) * 100
                son_basari = son_yari["toplam_dogru"].sum() / max(1, son_yari["toplam_soru"].sum()) * 100
                basari_degisim = son_basari - ilk_basari

                ilk_gunluk = ilk_yari["toplam_soru"].sum() / max(1, ilk_yari["tarih"].nunique())
                son_gunluk = son_yari["toplam_soru"].sum() / max(1, son_yari["tarih"].nunique())
                tempo_degisim = son_gunluk - ilk_gunluk
            else:
                basari_degisim = 0
                tempo_degisim = 0
                ilk_basari = ort_basari
                son_basari = ort_basari

            ders_analizleri.append({
                "ders": d,
                "durum": "ok",
                "toplam_soru": toplam_soru,
                "toplam_dogru": toplam_dogru,
                "toplam_yanlis": toplam_yanlis,
                "toplam_net": toplam_net,
                "ort_basari": ort_basari,
                "son_basari": son_basari,
                "ilk_basari": ilk_basari if not ilk_yari.empty else ort_basari,
                "basari_degisim": basari_degisim,
                "gun_sayisi": gun_sayisi,
                "gunluk_ort_soru": gunluk_ort_soru,
                "tempo_degisim": tempo_degisim,
            })

        aktif = [a for a in ders_analizleri if a["durum"] == "ok"]

        # ═══════════════════════════════════════════════════
        # TEK DERS SEÇİLDİYSE: DETAYLI ANALİZ
        # ═══════════════════════════════════════════════════
        if tek_ders and aktif:
            a = aktif[0]
            d = a["ders"]

            # ── 1. DETAYLI İSTATİSTİKLER ──
            self.analiz_text.insert(tk.END, "📊 DETAYLI İSTATİSTİKLER\n", "alt_baslik")
            self.analiz_text.insert(tk.END, f"  Ders: ", "normal")
            self.analiz_text.insert(tk.END, f"{d}\n", f"renk_{d}")
            self.analiz_text.insert(tk.END, f"  Çalışılan gün sayısı: {a['gun_sayisi']}\n", "normal")
            self.analiz_text.insert(tk.END, f"  Toplam çözülen soru: {a['toplam_soru']}\n", "normal")
            self.analiz_text.insert(tk.END, f"  Toplam doğru: {a['toplam_dogru']}  |  Toplam yanlış: {a['toplam_yanlis']}\n", "normal")
            self.analiz_text.insert(tk.END, f"  Toplam net: {a['toplam_net']:.1f}\n", "normal")
            self.analiz_text.insert(tk.END, f"  Ortalama başarı: ", "normal")
            tag = "iyi" if a["ort_basari"] >= 70 else ("kotu" if a["ort_basari"] < 50 else "uyari")
            self.analiz_text.insert(tk.END, f"%{a['ort_basari']:.1f}\n", tag)
            self.analiz_text.insert(tk.END, f"  Günlük ortalama soru: {a['gunluk_ort_soru']:.1f}\n", "normal")
            self.analiz_text.insert(tk.END, "\n", "normal")

            # ── 2. TREND ANALİZİ ──
            self.analiz_text.insert(tk.END, "📈 TREND ANALİZİ\n", "alt_baslik")
            if a["basari_degisim"] > 2:
                self.analiz_text.insert(tk.END, f"  İlk yarı başarı: %{a['ilk_basari']:.1f}  →  Son yarı başarı: %{a['son_basari']:.1f}\n", "normal")
                self.analiz_text.insert(tk.END, f"  Değişim: +{a['basari_degisim']:.1f}% ↑ Yükselen trend!\n", "iyi")
            elif a["basari_degisim"] < -2:
                self.analiz_text.insert(tk.END, f"  İlk yarı başarı: %{a['ilk_basari']:.1f}  →  Son yarı başarı: %{a['son_basari']:.1f}\n", "normal")
                self.analiz_text.insert(tk.END, f"  Değişim: {a['basari_degisim']:.1f}% ↓ Düşen trend!\n", "kotu")
            else:
                self.analiz_text.insert(tk.END, f"  Başarı oranı sabit seyir izliyor (%{a['ort_basari']:.1f})\n", "bilgi")

            if a["tempo_degisim"] > 2:
                self.analiz_text.insert(tk.END, f"  Çalışma temposu artıyor (+{a['tempo_degisim']:.1f} soru/gün) 👍\n", "iyi")
            elif a["tempo_degisim"] < -2:
                self.analiz_text.insert(tk.END, f"  Çalışma temposu düşüyor ({a['tempo_degisim']:.1f} soru/gün) ⚠️\n", "kotu")
            else:
                self.analiz_text.insert(tk.END, f"  Çalışma temposu sabit.\n", "bilgi")
            self.analiz_text.insert(tk.END, "\n", "normal")

            # ── 3. HAFTALIK PERFORMANS ──
            ders_df = df[df["ders"] == d].sort_values("tarih").copy()
            if len(ders_df) >= 7:
                self.analiz_text.insert(tk.END, "📅 HAFTALIK PERFORMANS\n", "alt_baslik")
                ders_df["hafta"] = ders_df["tarih"].dt.isocalendar().week.astype(int)
                haftalik = ders_df.groupby("hafta").agg(
                    soru=("toplam_soru", "sum"),
                    dogru=("toplam_dogru", "sum"),
                    net=("toplam_net", "sum"),
                    gun=("tarih", "nunique"),
                ).tail(6)
                for _, row in haftalik.iterrows():
                    basari_h = (row["dogru"] / max(1, row["soru"]) * 100)
                    tag_h = "iyi" if basari_h >= 70 else ("kotu" if basari_h < 50 else "uyari")
                    self.analiz_text.insert(tk.END, f"  Hafta {int(_):>2}: ", "normal")
                    self.analiz_text.insert(tk.END, f"{int(row['soru'])} soru  |  ", "normal")
                    self.analiz_text.insert(tk.END, f"%{basari_h:.0f} başarı", tag_h)
                    self.analiz_text.insert(tk.END, f"  |  {row['net']:.1f} net  |  {int(row['gun'])} gün\n", "normal")
                self.analiz_text.insert(tk.END, "\n", "normal")

            # ── 4. ÖZEL ÖNERİLER ──
            self.analiz_text.insert(tk.END, f"🎯 {d.upper()} İÇİN ÖNERİLER\n", "alt_baslik")

            if a["ort_basari"] < 40:
                self.analiz_text.insert(tk.END, f"  ⚠️  Başarı oranı çok düşük (%{a['ort_basari']:.1f}). Temel konu anlatımlarını baştan izle,\n", "kotu")
                self.analiz_text.insert(tk.END, f"     kolay sorulardan başlayarak kademe kademe zorlaştır.\n", "kotu")
            elif a["ort_basari"] < 60:
                self.analiz_text.insert(tk.END, f"  ⚠️  Başarı geliştirilmeli (%{a['ort_basari']:.1f}). Yanlış yaptığın soruları tekrar çöz,\n", "uyari")
                self.analiz_text.insert(tk.END, f"     eksik konulara odaklan ve konu testleri çöz.\n", "uyari")
            elif a["ort_basari"] < 80:
                self.analiz_text.insert(tk.END, f"  📌  İyi gidiyorsun (%{a['ort_basari']:.1f}). Pekiştirme testleri ve paragraf/yorum\n", "bilgi")
                self.analiz_text.insert(tk.END, f"     sorularına ağırlık ver. Zaman yönetimini de geliştir.\n", "bilgi")
            else:
                self.analiz_text.insert(tk.END, f"  🌟  Mükemmel performans (%{a['ort_basari']:.1f})! Zor ve nitelikli sorulara geç,\n", "iyi")
                self.analiz_text.insert(tk.END, f"     deneme sınavlarında bu dersten tam net hedefle.\n", "iyi")

            if a["basari_degisim"] < -3:
                self.analiz_text.insert(tk.END, f"  📉  Son dönemde başarı düşüyor. Yorgunluk veya konu zorluğu olabilir.\n", "kotu")
                self.analiz_text.insert(tk.END, f"     Kısa bir konu tekrarı yap, ardından kolaydan zora doğru soru çöz.\n", "kotu")

            if a["tempo_degisim"] < -3:
                self.analiz_text.insert(tk.END, f"  🐢  Çözüm temposu düşüyor. Günlük en az {max(15, int(a['gunluk_ort_soru']))} soru hedefi koy.\n", "uyari")

            if a["gun_sayisi"] < son_gun * 0.3:
                self.analiz_text.insert(tk.END, f"  📌  {son_gun} günde sadece {a['gun_sayisi']} gün çalışılmış. Düzenli çalışma çok önemli!\n", "uyari")
                self.analiz_text.insert(tk.END, f"     Her gün en az birkaç soru çözerek devamlılığı sağla.\n", "uyari")

            # Günlük hedef
            self.analiz_text.insert(tk.END, "\n", "normal")
            self.analiz_text.insert(tk.END, "📅 GÜNLÜK HEDEF\n", "alt_baslik")
            if a["ort_basari"] < 50:
                hedef = 30
                not_str = "Acil! Konu tekrarı + soru çöz"
            elif a["ort_basari"] < 65:
                hedef = 25
                not_str = "Zayıf konulara odaklan"
            elif a["ort_basari"] < 80:
                hedef = 20
                not_str = "Pekiştirme + yeni konular"
            else:
                hedef = 15
                not_str = "Seviyeyi koru, zor sorulara geç"
            self.analiz_text.insert(tk.END, f"  ", "normal")
            self.analiz_text.insert(tk.END, f"{d}", f"renk_{d}")
            self.analiz_text.insert(tk.END, f" → Minimum {hedef} soru/gün ", "oneri")
            self.analiz_text.insert(tk.END, f"({not_str})\n", "bilgi")

        elif tek_ders and not aktif:
            # Seçilen derste veri yok
            self.analiz_text.insert(tk.END, f"🚫 {secili_ders} dersinden henüz hiç soru çözülmemiş!\n", "kotu")
            self.analiz_text.insert(tk.END, f"   Hemen bu derse başla ve günlük en az 15-20 soru çöz.\n", "uyari")

        # ═══════════════════════════════════════════════════
        # TÜMÜ SEÇİLDİYSE: GENEL ANALİZ (mevcut davranış)
        # ═══════════════════════════════════════════════════
        else:
            # ── 1. GENEL DURUM ──
            self.analiz_text.insert(tk.END, "📊 GENEL ÖZET\n", "alt_baslik")
            if aktif:
                top_soru = sum(a["toplam_soru"] for a in aktif)
                top_net = sum(a["toplam_net"] for a in aktif)
                self.analiz_text.insert(tk.END, f"  Toplam çözülen soru: {top_soru}  |  Toplam net: {top_net:.1f}\n", "normal")
                en_cok = max(aktif, key=lambda x: x["toplam_soru"])
                en_az = min(aktif, key=lambda x: x["toplam_soru"])
                self.analiz_text.insert(tk.END, f"  En çok çalışılan: ", "normal")
                self.analiz_text.insert(tk.END, f"{en_cok['ders']} ({en_cok['toplam_soru']} soru)", f"renk_{en_cok['ders']}")
                self.analiz_text.insert(tk.END, f"  |  En az çalışılan: ", "normal")
                self.analiz_text.insert(tk.END, f"{en_az['ders']} ({en_az['toplam_soru']} soru)\n", f"renk_{en_az['ders']}")
            self.analiz_text.insert(tk.END, "\n", "normal")

            # ── 2. DERS BAZINDA DURUM ──
            self.analiz_text.insert(tk.END, "📖 DERS BAZINDA PERFORMANS\n", "alt_baslik")
            for a in sorted(aktif, key=lambda x: x["ort_basari"]):
                d = a["ders"]
                trend_icon = "📈" if a["basari_degisim"] > 2 else ("📉" if a["basari_degisim"] < -2 else "➡️")
                tag = "iyi" if a["ort_basari"] >= 70 else ("kotu" if a["ort_basari"] < 50 else "uyari")

                self.analiz_text.insert(tk.END, f"  {trend_icon} ", "normal")
                self.analiz_text.insert(tk.END, f"{d}", f"renk_{d}")
                self.analiz_text.insert(tk.END, f"  → Başarı: %{a['ort_basari']:.1f}", tag)

                if a["basari_degisim"] > 2:
                    self.analiz_text.insert(tk.END, f"  (+{a['basari_degisim']:.1f}% ↑)", "iyi")
                elif a["basari_degisim"] < -2:
                    self.analiz_text.insert(tk.END, f"  ({a['basari_degisim']:.1f}% ↓)", "kotu")
                else:
                    self.analiz_text.insert(tk.END, f"  (sabit)", "bilgi")

                self.analiz_text.insert(tk.END, f"  |  Günlük ort: {a['gunluk_ort_soru']:.0f} soru  |  Net: {a['toplam_net']:.1f}\n", "normal")

            self.analiz_text.insert(tk.END, "\n", "normal")

            # ── 3. ÖNCELİKLİ ÇALIŞMA ÖNERİLERİ ──
            self.analiz_text.insert(tk.END, "🎯 ÖNCELİKLİ ÇALIŞMA ÖNERİLERİ\n", "alt_baslik")

            oneriler = []

            # Düşük başarı oranı
            dusuk_basari = [a for a in aktif if a["ort_basari"] < 60]
            for a in sorted(dusuk_basari, key=lambda x: x["ort_basari"]):
                oneriler.append((
                    "kotu",
                    f"⚠️  {a['ders']} dersi başarı oranı düşük (%{a['ort_basari']:.1f}). "
                    f"Bu derste konu tekrarı yaparak temel eksikleri kapatmalısın.\n"
                ))

            # Düşen trend
            dusen = [a for a in aktif if a["basari_degisim"] < -3]
            for a in sorted(dusen, key=lambda x: x["basari_degisim"]):
                oneriler.append((
                    "kotu",
                    f"📉  {a['ders']} dersinde başarı düşüyor ({a['basari_degisim']:.1f}%). "
                    f"Yanlış yaptığın konuları tespit edip o konulara odaklan.\n"
                ))

            # Az çalışılan dersler
            if aktif:
                ort_soru = sum(a["toplam_soru"] for a in aktif) / len(aktif)
                az_calisan = [a for a in aktif if a["toplam_soru"] < ort_soru * 0.6]
                for a in az_calisan:
                    oneriler.append((
                        "uyari",
                        f"📌  {a['ders']} dersi ortalamanın altında çalışılıyor "
                        f"({a['toplam_soru']} soru, ort: {ort_soru:.0f}). Daha fazla soru çözmelisin.\n"
                    ))

            # Tempo düşüşü
            tempo_dusen = [a for a in aktif if a["tempo_degisim"] < -3]
            for a in tempo_dusen:
                oneriler.append((
                    "uyari",
                    f"🐢  {a['ders']} dersinde çözüm temposu düşüyor. "
                    f"Günlük hedef belirleyerek düzenli çalışmayı sürdür.\n"
                ))

            # Yükselen trendler (pozitif mesaj)
            yukselenler = [a for a in aktif if a["basari_degisim"] > 5]
            for a in yukselenler:
                oneriler.append((
                    "iyi",
                    f"🌟  {a['ders']} dersinde harika ilerleme! (+{a['basari_degisim']:.1f}%) "
                    f"Bu tempoyu korumaya devam et.\n"
                ))

            # Çalışılmayan dersler
            calisilmayan = [a for a in ders_analizleri if a["durum"] == "veri_yok"]
            for a in calisilmayan:
                oneriler.append((
                    "kotu",
                    f"🚫  {a['ders']} dersinden hiç soru çözülmemiş! Hemen bu derse başlamalısın.\n"
                ))

            if oneriler:
                for tag, oneri in oneriler:
                    self.analiz_text.insert(tk.END, f"  {oneri}", tag)
            else:
                self.analiz_text.insert(tk.END, "  ✅ Tebrikler! Tüm derslerde dengeli ve iyi bir performans gösteriyorsun.\n", "iyi")

            self.analiz_text.insert(tk.END, "\n", "normal")

            # ── 4. ÇALIŞMA PLANI ÖNERİSİ ──
            self.analiz_text.insert(tk.END, "📅 GÜNLÜK ÇALIŞMA PLANI ÖNERİSİ\n", "alt_baslik")

            if aktif:
                # Öncelik sıralaması: düşük başarı + az çalışılan önce
                oncelik = sorted(aktif, key=lambda x: (x["ort_basari"], x["toplam_soru"]))

                self.analiz_text.insert(tk.END, "  Öncelik sırasına göre günlük minimum hedefler:\n", "normal")
                for i, a in enumerate(oncelik, 1):
                    d = a["ders"]
                    # Başarıya göre hedef soru sayısı belirle
                    if a["ort_basari"] < 50:
                        hedef = 30
                        not_str = "(Acil! Konu tekrarı + soru çöz)"
                    elif a["ort_basari"] < 65:
                        hedef = 25
                        not_str = "(Zayıf konulara odaklan)"
                    elif a["ort_basari"] < 80:
                        hedef = 20
                        not_str = "(Pekiştirme + yeni konular)"
                    else:
                        hedef = 15
                        not_str = "(Seviyeyi koru, zor sorulara geç)"

                    self.analiz_text.insert(tk.END, f"  {i}. ", "normal")
                    self.analiz_text.insert(tk.END, f"{d}", f"renk_{d}")
                    self.analiz_text.insert(tk.END, f" → Minimum {hedef} soru/gün ", "oneri")
                    self.analiz_text.insert(tk.END, f"{not_str}\n", "bilgi")

        self.analiz_text.insert(tk.END, "\n═" * 1 + "═" * 60 + "\n", "normal")
        self.analiz_text.insert(tk.END, "💡 İpucu: ", "alt_baslik")
        self.analiz_text.insert(
            tk.END,
            "Trend çizgisi (kesikli) yukarı gidiyorsa gelişiyorsun demektir. "
            "Hedefin tüm derslerde trend çizgisini yukarı yönlü tutmak olmalı!\n",
            "bilgi",
        )

        self.analiz_text.configure(state=tk.DISABLED)

    # =====================================================
    # SEKME 5: LGS SINAVLARI
    # =====================================================
    def _build_sinav_tab(self):
        """LGS Sınavları sekmesi."""
        tab = ttkb.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="  📑 LGS Sınavları  ")

        # Üst: Sol=Form, Sağ=Liste (Panedwindow ile boyutlandırılabilir)
        ust_paned = ttkb.Panedwindow(tab, orient=tk.HORIZONTAL)
        ust_paned.pack(fill=BOTH, expand=True)

        # ── SOL PANEL: Sınav Giriş Formu ──
        sol_frame = ttkb.Frame(ust_paned)
        ust_paned.add(sol_frame, weight=3)

        # Kurum yönetimi + sınav formu (notebook içinde)
        sinav_nb = ttkb.Notebook(sol_frame, bootstyle="info")
        sinav_nb.pack(fill=BOTH, expand=True)

        # --- Alt Sekme 1: Sınav Girişi ---
        form_tab = ttkb.Frame(sinav_nb, padding=10)
        sinav_nb.add(form_tab, text=" 📝 Sınav Girişi ")

        # Form alanı (scrollable)
        form_canvas = tk.Canvas(form_tab, highlightthickness=0)
        form_scrollbar = ttkb.Scrollbar(form_tab, orient=VERTICAL, command=form_canvas.yview)
        form_inner = ttkb.Frame(form_canvas)

        form_inner.bind("<Configure>", lambda e: form_canvas.configure(scrollregion=form_canvas.bbox("all")))
        form_canvas.create_window((0, 0), window=form_inner, anchor="nw")
        form_canvas.configure(yscrollcommand=form_scrollbar.set)

        form_canvas.pack(side=LEFT, fill=BOTH, expand=True)
        form_scrollbar.pack(side=RIGHT, fill=Y)

        row = 0
        # Sınav adı
        ttkb.Label(form_inner, text="📋 Sınav Adı:", font=("Segoe UI", 10)).grid(
            row=row, column=0, sticky=W, pady=4, padx=5)
        self.sinav_adi_var = tk.StringVar()
        ttkb.Entry(form_inner, textvariable=self.sinav_adi_var, font=("Segoe UI", 10), width=30).grid(
            row=row, column=1, columnspan=2, sticky=EW, pady=4, padx=5)

        row += 1
        # Sınav tarihi
        ttkb.Label(form_inner, text="📅 Sınav Tarihi:", font=("Segoe UI", 10)).grid(
            row=row, column=0, sticky=W, pady=4, padx=5)
        self.sinav_tarihi_var = tk.StringVar(value=date.today().strftime("%Y-%m-%d"))
        ttkb.Entry(form_inner, textvariable=self.sinav_tarihi_var, font=("Segoe UI", 10), width=15).grid(
            row=row, column=1, sticky=W, pady=4, padx=5)

        row += 1
        # Kurum seçimi
        ttkb.Label(form_inner, text="🏢 Kurum:", font=("Segoe UI", 10)).grid(
            row=row, column=0, sticky=W, pady=4, padx=5)
        self.sinav_kurum_var = tk.StringVar(value="(Seçiniz)")
        self.sinav_kurum_combo = ttkb.Combobox(
            form_inner, textvariable=self.sinav_kurum_var,
            state="readonly", font=("Segoe UI", 10), width=25)
        self.sinav_kurum_combo.grid(row=row, column=1, sticky=EW, pady=4, padx=5)
        self._kurum_combo_guncelle()

        row += 1
        # Puan
        ttkb.Label(form_inner, text="🎯 Puan:", font=("Segoe UI", 10)).grid(
            row=row, column=0, sticky=W, pady=4, padx=5)
        self.sinav_puan_var = tk.StringVar()
        ttkb.Entry(form_inner, textvariable=self.sinav_puan_var, font=("Segoe UI", 10), width=12).grid(
            row=row, column=1, sticky=W, pady=4, padx=5)

        row += 1
        # Dereceler
        ttkb.Label(form_inner, text="🏆 Dereceler:", font=("Segoe UI", 10, "bold")).grid(
            row=row, column=0, columnspan=3, sticky=W, pady=(10, 4), padx=5)

        row += 1
        derece_frame = ttkb.Frame(form_inner)
        derece_frame.grid(row=row, column=0, columnspan=3, sticky=EW, pady=4, padx=5)

        derece_items = [("Genel", "genel"), ("İl", "il"), ("İlçe", "ilce"), ("Kurum", "kurum"), ("Şube", "sube")]
        self.derece_vars = {}
        for i, (lbl, key) in enumerate(derece_items):
            ttkb.Label(derece_frame, text=f"{lbl}:", font=("Segoe UI", 9)).grid(row=0, column=i*2, padx=2)
            var = tk.StringVar()
            self.derece_vars[key] = var
            ttkb.Entry(derece_frame, textvariable=var, width=6, font=("Segoe UI", 9)).grid(
                row=0, column=i*2+1, padx=2)

        row += 1
        # Ders sonuçları başlığı
        ttkb.Label(form_inner, text="📖 Ders Sonuçları:", font=("Segoe UI", 10, "bold")).grid(
            row=row, column=0, columnspan=3, sticky=W, pady=(10, 4), padx=5)

        row += 1
        # Ders başlıkları
        ders_header = ttkb.Frame(form_inner)
        ders_header.grid(row=row, column=0, columnspan=3, sticky=EW, padx=5)
        ttkb.Label(ders_header, text="Ders", font=("Segoe UI", 9, "bold"), width=12).grid(row=0, column=0)
        ttkb.Label(ders_header, text="S.Sayı", font=("Segoe UI", 9, "bold"), width=6).grid(row=0, column=1)
        ttkb.Label(ders_header, text="Doğru", font=("Segoe UI", 9, "bold"), width=6).grid(row=0, column=2)
        ttkb.Label(ders_header, text="Yanlış", font=("Segoe UI", 9, "bold"), width=6).grid(row=0, column=3)
        ttkb.Label(ders_header, text="Net", font=("Segoe UI", 9, "bold"), width=8).grid(row=0, column=4)

        # LGS ders soru sayıları
        lgs_soru = {"Türkçe": 20, "Matematik": 20, "Fen": 20, "Sosyal": 10, "İngilizce": 10, "Din": 10}

        self.sinav_ders_vars = {}
        for i, ders in enumerate(DERSLER):
            row += 1
            df = ttkb.Frame(form_inner)
            df.grid(row=row, column=0, columnspan=3, sticky=EW, padx=5, pady=1)

            renk = DERS_RENKLERI[ders]
            ttkb.Label(df, text=f"● {ders}", font=("Segoe UI", 9), foreground=renk, width=12).grid(
                row=0, column=0, sticky=W)

            ss_var = tk.StringVar(value=str(lgs_soru.get(ders, 10)))
            d_var = tk.StringVar(value="0")
            y_var = tk.StringVar(value="0")
            net_lbl = ttkb.Label(df, text="0.00", font=("Segoe UI", 9, "bold"), width=8)

            ttkb.Entry(df, textvariable=ss_var, width=6, font=("Segoe UI", 9)).grid(row=0, column=1)
            ttkb.Entry(df, textvariable=d_var, width=6, font=("Segoe UI", 9)).grid(row=0, column=2)
            ttkb.Entry(df, textvariable=y_var, width=6, font=("Segoe UI", 9)).grid(row=0, column=3)
            net_lbl.grid(row=0, column=4)

            self.sinav_ders_vars[ders] = {"ss": ss_var, "d": d_var, "y": y_var, "net_lbl": net_lbl}

            # LGS net hesaplama (3 yanlış 1 doğruyu götürür)
            def _calc_net(ders_key=ders, *args):
                try:
                    v = self.sinav_ders_vars[ders_key]
                    d = int(v["d"].get() or 0)
                    y = int(v["y"].get() or 0)
                    net = d - (y / 3.0)
                    v["net_lbl"].configure(text=f"{net:.2f}")
                except ValueError:
                    pass

            d_var.trace_add("write", _calc_net)
            y_var.trace_add("write", _calc_net)

        row += 1
        # Toplam net göstergesi
        toplam_frame = ttkb.Frame(form_inner)
        toplam_frame.grid(row=row, column=0, columnspan=3, sticky=EW, padx=5, pady=(8, 4))
        ttkb.Label(toplam_frame, text="TOPLAM NET:", font=("Segoe UI", 11, "bold")).pack(side=LEFT)
        self.sinav_toplam_net_lbl = ttkb.Label(toplam_frame, text="0.00",
            font=("Segoe UI", 14, "bold"), bootstyle="success")
        self.sinav_toplam_net_lbl.pack(side=LEFT, padx=10)

        # Toplam net otomatik hesaplama
        def _calc_toplam(*args):
            toplam = 0.0
            for ders in DERSLER:
                try:
                    v = self.sinav_ders_vars[ders]
                    d = int(v["d"].get() or 0)
                    y = int(v["y"].get() or 0)
                    toplam += d - (y / 3.0)
                except ValueError:
                    pass
            self.sinav_toplam_net_lbl.configure(text=f"{toplam:.2f}")

        for ders in DERSLER:
            self.sinav_ders_vars[ders]["d"].trace_add("write", _calc_toplam)
            self.sinav_ders_vars[ders]["y"].trace_add("write", _calc_toplam)

        row += 1
        # Butonlar
        btn_frame = ttkb.Frame(form_inner)
        btn_frame.grid(row=row, column=0, columnspan=3, pady=10)

        self.sinav_kaydet_btn = ttkb.Button(btn_frame, text="💾 Sınavı Kaydet",
            command=self._sinav_kaydet, bootstyle="success", width=18)
        self.sinav_kaydet_btn.pack(side=LEFT, padx=5)

        ttkb.Button(btn_frame, text="🔄 Temizle",
            command=self._sinav_formu_temizle, bootstyle="secondary-outline", width=12).pack(side=LEFT, padx=5)

        self._sinav_edit_id = None  # Düzenleme modu için

        form_inner.columnconfigure(1, weight=1)

        # --- Alt Sekme 2: Kurum Yönetimi ---
        kurum_tab = ttkb.Frame(sinav_nb, padding=10)
        sinav_nb.add(kurum_tab, text=" 🏢 Kurum Yönetimi ")

        ttkb.Label(kurum_tab, text="Yeni Kurum Ekle:", font=("Segoe UI", 10)).pack(anchor=W, pady=(0, 5))

        kurum_input_frame = ttkb.Frame(kurum_tab)
        kurum_input_frame.pack(fill=X, pady=(0, 10))

        self.yeni_kurum_var = tk.StringVar()
        ttkb.Entry(kurum_input_frame, textvariable=self.yeni_kurum_var,
            font=("Segoe UI", 10), width=25).pack(side=LEFT, padx=(0, 5))
        ttkb.Button(kurum_input_frame, text="➕ Ekle",
            command=self._kurum_ekle, bootstyle="success", width=10).pack(side=LEFT)

        ttkb.Label(kurum_tab, text="Mevcut Kurumlar:", font=("Segoe UI", 10)).pack(anchor=W, pady=(10, 5))

        self.kurum_listbox = tk.Listbox(kurum_tab, font=("Segoe UI", 10), height=10)
        self.kurum_listbox.pack(fill=BOTH, expand=True, pady=(0, 5))

        kurum_btn_frame = ttkb.Frame(kurum_tab)
        kurum_btn_frame.pack(fill=X)
        ttkb.Button(kurum_btn_frame, text="🗑️ Sil",
            command=self._kurum_sil, bootstyle="danger-outline", width=10).pack(side=LEFT, padx=5)
        ttkb.Button(kurum_btn_frame, text="✏️ Ad Değiştir",
            command=self._kurum_duzenle, bootstyle="warning-outline", width=12).pack(side=LEFT, padx=5)

        self._kurum_listesini_guncelle()

        # --- Alt Sekme 3: Sınav Karşılaştırma Grafikleri ---
        grafik_tab = ttkb.Frame(sinav_nb, padding=10)
        sinav_nb.add(grafik_tab, text=" 📊 Sınav Karşılaştırma ")

        # Filtre
        gf_filter = ttkb.Frame(grafik_tab)
        gf_filter.pack(fill=X, pady=(0, 10))

        ttkb.Label(gf_filter, text="Kurum:", font=("Segoe UI", 10)).pack(side=LEFT, padx=5)
        self.sinav_grafik_kurum_var = tk.StringVar(value="Tümü")
        self.sinav_grafik_kurum_combo = ttkb.Combobox(
            gf_filter, textvariable=self.sinav_grafik_kurum_var,
            state="readonly", font=("Segoe UI", 10), width=20)
        self.sinav_grafik_kurum_combo.pack(side=LEFT, padx=5)

        ttkb.Label(gf_filter, text="Grafik:", font=("Segoe UI", 10)).pack(side=LEFT, padx=5)
        self.sinav_grafik_tip_var = tk.StringVar(value="Puan Gelişimi (Line)")
        ttkb.Combobox(
            gf_filter, textvariable=self.sinav_grafik_tip_var,
            values=["Puan Gelişimi (Line)", "Net Gelişimi (Line)",
                    "Derece Gelişimi (Line)", "Ders Netleri Karşılaştırma (Bar)"],
            state="readonly", font=("Segoe UI", 10), width=28).pack(side=LEFT, padx=5)

        ttkb.Button(gf_filter, text="📊 Göster",
            command=self._sinav_grafik_guncelle, bootstyle="success").pack(side=LEFT, padx=10)

        self.sinav_grafik_frame = ttkb.Frame(grafik_tab)
        self.sinav_grafik_frame.pack(fill=BOTH, expand=True)

        self._sinav_grafik_kurum_combo_guncelle()

        # ── SAĞ PANEL: Sınav Listesi ──
        sag_frame = ttkb.Labelframe(ust_paned, text="Sınav Kayıtları", padding=10, bootstyle="primary")
        ust_paned.add(sag_frame, weight=2)

        # Filtre
        sinav_filter = ttkb.Frame(sag_frame)
        sinav_filter.pack(fill=X, pady=(0, 5))

        ttkb.Label(sinav_filter, text="Kurum:", font=("Segoe UI", 9)).pack(side=LEFT, padx=2)
        self.sinav_liste_kurum_var = tk.StringVar(value="Tümü")
        self.sinav_liste_kurum_combo = ttkb.Combobox(
            sinav_filter, textvariable=self.sinav_liste_kurum_var,
            state="readonly", font=("Segoe UI", 9), width=15)
        self.sinav_liste_kurum_combo.pack(side=LEFT, padx=2)
        # Kurum seçimi değiştiğinde tabloyu beklemeden otomatik filtrele.
        self.sinav_liste_kurum_combo.bind(
            "<<ComboboxSelected>>",
            lambda _event: self._sinav_listesini_guncelle()
        )

        # Eylem butonları: emojisiz ve yeterli genişlikte, yazılar düzgün görünsün.
        ttkb.Button(sinav_filter, text="Sil", command=self._sinav_sil,
            bootstyle="danger-outline", width=7).pack(side=RIGHT, padx=2)
        ttkb.Button(sinav_filter, text="Düzenle", command=self._sinav_duzenle,
            bootstyle="warning-outline", width=9).pack(side=RIGHT, padx=2)

        # Tablo
        cols = ("id", "tarih", "sinav", "kurum", "puan", "genel", "toplam_net")
        self.sinav_tablo = ttkb.Treeview(
            sag_frame, columns=cols, show="headings", bootstyle="info", height=8)

        headers_w = {
            "id": ("ID", 35), "tarih": ("Tarih", 80), "sinav": ("Sınav", 130),
            "kurum": ("Kurum", 90), "puan": ("Puan", 65),
            "genel": ("Genel", 55), "toplam_net": ("T.Net", 55)
        }
        # Sütun başlıklarına tıklayarak sıralama yapılabilir.
        self._sinav_siralama_durum = {}
        for col, (h, w) in headers_w.items():
            self.sinav_tablo.heading(
                col, text=h,
                command=lambda c=col: self._sinav_tablo_sirala(c)
            )
            self.sinav_tablo.column(col, width=w, anchor=CENTER if col != "sinav" else W)

        # Filtreye göre listelenen sınav sayısı.
        self.sinav_sayisi_label = ttkb.Label(
            sag_frame, text="Toplam sınav: 0",
            font=("Segoe UI", 9, "bold"), bootstyle="primary"
        )
        self.sinav_sayisi_label.pack(side=BOTTOM, anchor=E, fill=X, pady=(6, 0))

        sinav_scroll = ttkb.Scrollbar(sag_frame, orient=VERTICAL, command=self.sinav_tablo.yview)
        self.sinav_tablo.configure(yscrollcommand=sinav_scroll.set)
        self.sinav_tablo.pack(side=LEFT, fill=BOTH, expand=True)
        sinav_scroll.pack(side=RIGHT, fill=Y)

        # Alt: Sınav detayı
        self.sinav_detay_frame = ttkb.Labelframe(tab, text="Sınav Detayı", padding=10, bootstyle="secondary")
        self.sinav_detay_frame.pack(fill=X, pady=(5, 0))

        self.sinav_detay_text = tk.Text(
            self.sinav_detay_frame, wrap=tk.WORD, font=("Segoe UI", 9),
            bg="#f8f9fa", fg="#2c3e50", relief=tk.FLAT, height=5, padx=8, pady=5)
        self.sinav_detay_text.pack(fill=X)
        self.sinav_detay_text.configure(state=tk.DISABLED)

        # Sınav seçildiğinde detay göster
        self.sinav_tablo.bind("<<TreeviewSelect>>", self._sinav_detay_goster)

        self._sinav_liste_kurum_combo_guncelle()

    # ── Kurum işlemleri ──
    def _kurum_combo_guncelle(self):
        """Kurum combo listesini güncelle."""
        kurumlar = db.kurumlari_getir()
        self._kurum_listesi = kurumlar
        values = ["(Seçiniz)"] + [k["kurum_adi"] for k in kurumlar]
        self.sinav_kurum_combo.configure(values=values)

    def _kurum_listesini_guncelle(self):
        """Kurum listbox güncelle."""
        self.kurum_listbox.delete(0, tk.END)
        kurumlar = db.kurumlari_getir()
        self._kurum_listesi = kurumlar
        for k in kurumlar:
            self.kurum_listbox.insert(tk.END, k["kurum_adi"])

    def _kurum_ekle(self):
        """Yeni kurum ekle."""
        adi = self.yeni_kurum_var.get().strip()
        if not adi:
            Messagebox.show_warning("Kurum adı boş olamaz!", "Uyarı")
            return
        result = db.kurum_ekle(adi)
        if result == -1:
            Messagebox.show_warning("Bu kurum zaten mevcut!", "Uyarı")
        else:
            self.yeni_kurum_var.set("")
            self._kurum_listesini_guncelle()
            self._kurum_combo_guncelle()
            self._sinav_grafik_kurum_combo_guncelle()
            self._sinav_liste_kurum_combo_guncelle()
            Messagebox.show_info(f"'{adi}' eklendi!", "Başarılı")

    def _kurum_sil(self):
        """Seçili kurumu sil."""
        sel = self.kurum_listbox.curselection()
        if not sel:
            Messagebox.show_warning("Lütfen silmek istediğiniz kurumu seçin!", "Uyarı")
            return
        kurum = self._kurum_listesi[sel[0]]
        confirm = Messagebox.yesno(f"'{kurum['kurum_adi']}' silinsin mi?\nBu kuruma ait sınavların kurum bilgisi kaldırılacak.", "Onay")
        if confirm == "Yes":
            db.kurum_sil(kurum["id"])
            self._kurum_listesini_guncelle()
            self._kurum_combo_guncelle()
            self._sinav_grafik_kurum_combo_guncelle()
            self._sinav_liste_kurum_combo_guncelle()

    def _kurum_duzenle(self):
        """Seçili kurum adını değiştir."""
        sel = self.kurum_listbox.curselection()
        if not sel:
            Messagebox.show_warning("Lütfen düzenlemek istediğiniz kurumu seçin!", "Uyarı")
            return
        kurum = self._kurum_listesi[sel[0]]

        # Basit dialog
        dlg = ttkb.Toplevel(self.root)
        dlg.title("Kurum Adı Değiştir")
        dlg.geometry("350x120")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()

        ttkb.Label(dlg, text="Yeni kurum adı:", font=("Segoe UI", 10)).pack(pady=(15, 5))
        yeni_ad_var = tk.StringVar(value=kurum["kurum_adi"])
        entry = ttkb.Entry(dlg, textvariable=yeni_ad_var, font=("Segoe UI", 10), width=30)
        entry.pack(pady=5)
        entry.select_range(0, tk.END)
        entry.focus()

        def _kaydet():
            yeni = yeni_ad_var.get().strip()
            if yeni:
                db.kurum_guncelle(kurum["id"], yeni)
                self._kurum_listesini_guncelle()
                self._kurum_combo_guncelle()
                self._sinav_grafik_kurum_combo_guncelle()
                self._sinav_liste_kurum_combo_guncelle()
                dlg.destroy()

        ttkb.Button(dlg, text="Kaydet", command=_kaydet, bootstyle="success").pack(pady=5)

    # ── Sınav CRUD ──
    def _sinav_kaydet(self):
        """Sınav kaydını ekle veya güncelle."""
        sinav_adi = self.sinav_adi_var.get().strip()
        if not sinav_adi:
            Messagebox.show_error("Sınav adı boş olamaz!", "Hata")
            return

        sinav_tarihi = self.sinav_tarihi_var.get().strip()
        if not sinav_tarihi:
            Messagebox.show_error("Sınav tarihi boş olamaz!", "Hata")
            return

        # Kurum
        kurum_adi = self.sinav_kurum_var.get()
        kurum_id = None
        if kurum_adi != "(Seçiniz)":
            for k in self._kurum_listesi:
                if k["kurum_adi"] == kurum_adi:
                    kurum_id = k["id"]
                    break

        # Puan
        puan = None
        try:
            if self.sinav_puan_var.get().strip():
                puan = float(self.sinav_puan_var.get())
        except ValueError:
            Messagebox.show_error("Puan geçerli bir sayı olmalı!", "Hata")
            return

        # Dereceler
        def _get_int(var):
            try:
                if var is None:
                    return None
                v = var.get().strip()
                return int(v) if v else None
            except (ValueError, AttributeError):
                return None

        genel = _get_int(self.derece_vars.get("genel"))
        il_d = _get_int(self.derece_vars.get("il"))
        ilce = _get_int(self.derece_vars.get("ilce"))
        kurum_d = _get_int(self.derece_vars.get("kurum"))
        sube = _get_int(self.derece_vars.get("sube"))

        # Kaydet veya güncelle
        if self._sinav_edit_id:
            sinav_id = self._sinav_edit_id
            db.sinav_guncelle(sinav_id, sinav_adi, sinav_tarihi, kurum_id,
                             puan, genel, il_d, ilce, kurum_d, sube)
            db.sinav_dersleri_sil(sinav_id)
        else:
            sinav_id = db.sinav_ekle(sinav_adi, sinav_tarihi, kurum_id,
                                    puan, genel, il_d, ilce, kurum_d, sube)

        # Ders sonuçlarını kaydet
        for ders in DERSLER:
            v = self.sinav_ders_vars[ders]
            try:
                ss = int(v["ss"].get() or 0)
                d = int(v["d"].get() or 0)
                y = int(v["y"].get() or 0)
                if ss > 0 or d > 0 or y > 0:
                    db.sinav_ders_ekle(sinav_id, ders, ss, d, y)
            except ValueError:
                pass

        msg = "güncellendi" if self._sinav_edit_id else "kaydedildi"
        Messagebox.show_info(f"Sınav başarıyla {msg}!", "Başarılı")
        self._sinav_formu_temizle()
        self._sinav_listesini_guncelle()

    def _sinav_formu_temizle(self):
        """Sınav formunu temizle."""
        self._sinav_edit_id = None
        self.sinav_kaydet_btn.configure(text="💾 Sınavı Kaydet")
        self.sinav_adi_var.set("")
        self.sinav_tarihi_var.set(date.today().strftime("%Y-%m-%d"))
        self.sinav_kurum_var.set("(Seçiniz)")
        self.sinav_puan_var.set("")
        for var in self.derece_vars.values():
            var.set("")
        lgs_soru = {"Türkçe": 20, "Matematik": 20, "Fen": 20, "Sosyal": 10, "İngilizce": 10, "Din": 10}
        for ders in DERSLER:
            self.sinav_ders_vars[ders]["ss"].set(str(lgs_soru.get(ders, 10)))
            self.sinav_ders_vars[ders]["d"].set("0")
            self.sinav_ders_vars[ders]["y"].set("0")

    def _sinav_tablo_sirala(self, sutun):
        """Sınav tablosunu seçilen sütuna göre artan/azalan sırala."""
        items = [(self.sinav_tablo.set(item, sutun), item)
                 for item in self.sinav_tablo.get_children("")]

        # Aynı sütuna tekrar tıklanınca sıralama yönünü tersine çevir.
        ters = self._sinav_siralama_durum.get(sutun, False)

        def anahtar(kayit):
            deger, _item = kayit
            if sutun == "tarih":
                try:
                    return datetime.strptime(deger, "%d.%m.%Y")
                except (ValueError, TypeError):
                    return datetime.min
            if sutun in ("id", "puan", "genel", "toplam_net"):
                try:
                    return float(deger.replace(",", "."))
                except (ValueError, AttributeError):
                    return float("-inf")
            return (deger or "").casefold()

        items.sort(key=anahtar, reverse=ters)
        for index, (_deger, item) in enumerate(items):
            self.sinav_tablo.move(item, "", index)

        self._sinav_siralama_durum[sutun] = not ters

    def _sinav_listesini_guncelle(self):
        """Sınav listesini güncelle."""
        for item in self.sinav_tablo.get_children():
            self.sinav_tablo.delete(item)

        # Kurum filtresi
        kurum_adi = self.sinav_liste_kurum_var.get()
        kurum_id = None
        if kurum_adi != "Tümü":
            for k in self._kurum_listesi:
                if k["kurum_adi"] == kurum_adi:
                    kurum_id = k["id"]
                    break

        sinavlar = db.sinavlari_getir(kurum_id=kurum_id)
        self.sinav_sayisi_label.configure(text=f"Toplam sınav: {len(sinavlar)}")

        for s in sinavlar:
            # Toplam net hesapla
            detay = db.sinav_detay_getir(s["id"])
            toplam_net = sum(d["net"] for d in detay["dersler"]) if detay and detay["dersler"] else 0

            tarih_str = datetime.strptime(s["sinav_tarihi"], "%Y-%m-%d").strftime("%d.%m.%Y")
            puan_str = f"{s['puan']:.1f}" if s["puan"] else "-"
            genel_str = str(s["genel_derece"]) if s["genel_derece"] else "-"
            kurum_str = s["kurum_adi"] or "-"

            self.sinav_tablo.insert("", END, values=(
                s["id"], tarih_str, s["sinav_adi"], kurum_str,
                puan_str, genel_str, f"{toplam_net:.1f}"
            ))

    def _sinav_detay_goster(self, event=None):
        """Seçili sınavın detaylarını göster."""
        sel = self.sinav_tablo.selection()
        if not sel:
            return

        sinav_id = int(self.sinav_tablo.item(sel[0], "values")[0])
        detay = db.sinav_detay_getir(sinav_id)
        if not detay:
            return

        s = detay["sinav"]
        self.sinav_detay_text.configure(state=tk.NORMAL)
        self.sinav_detay_text.delete("1.0", tk.END)

        tarih_str = datetime.strptime(s["sinav_tarihi"], "%Y-%m-%d").strftime("%d.%m.%Y")
        kurum_str = s.get("kurum_adi") or "Belirtilmemiş"

        header = f"📋 {s['sinav_adi']}  |  📅 {tarih_str}  |  🏢 {kurum_str}"
        if s["puan"]:
            header += f"  |  🎯 Puan: {s['puan']:.2f}"
        self.sinav_detay_text.insert(tk.END, header + "\n")

        # Dereceler
        dereceler = []
        if s["genel_derece"]: dereceler.append(f"Genel: {s['genel_derece']}")
        if s["il_derece"]: dereceler.append(f"İl: {s['il_derece']}")
        if s["ilce_derece"]: dereceler.append(f"İlçe: {s['ilce_derece']}")
        if s["kurum_derece"]: dereceler.append(f"Kurum: {s['kurum_derece']}")
        if s["sube_derece"]: dereceler.append(f"Şube: {s['sube_derece']}")
        if dereceler:
            self.sinav_detay_text.insert(tk.END, f"🏆 Dereceler: {' | '.join(dereceler)}\n")

        # Ders sonuçları
        if detay["dersler"]:
            self.sinav_detay_text.insert(tk.END, f"{'Ders':<14} {'S.Sayı':>6} {'Doğru':>6} {'Yanlış':>7} {'Net':>8}\n")
            self.sinav_detay_text.insert(tk.END, "-" * 46 + "\n")
            toplam_net = 0
            for d in detay["dersler"]:
                self.sinav_detay_text.insert(tk.END,
                    f"{d['ders']:<14} {d['soru_sayisi']:>6} {d['dogru']:>6} {d['yanlis']:>7} {d['net']:>8.2f}\n")
                toplam_net += d["net"]
            self.sinav_detay_text.insert(tk.END, "-" * 46 + "\n")
            self.sinav_detay_text.insert(tk.END, f"{'TOPLAM NET':<14} {'':>6} {'':>6} {'':>7} {toplam_net:>8.2f}\n")

        self.sinav_detay_text.configure(state=tk.DISABLED)

    def _sinav_duzenle(self):
        """Seçili sınavı düzenleme moduna al."""
        sel = self.sinav_tablo.selection()
        if not sel:
            Messagebox.show_warning("Lütfen düzenlemek istediğiniz sınavı seçin!", "Uyarı")
            return

        sinav_id = int(self.sinav_tablo.item(sel[0], "values")[0])
        detay = db.sinav_detay_getir(sinav_id)
        if not detay:
            return

        s = detay["sinav"]
        self._sinav_edit_id = sinav_id
        self.sinav_kaydet_btn.configure(text="💾 Güncelle")

        self.sinav_adi_var.set(s["sinav_adi"])
        self.sinav_tarihi_var.set(s["sinav_tarihi"])

        # Kurum
        kurum_adi = s.get("kurum_adi")
        if kurum_adi:
            self.sinav_kurum_var.set(kurum_adi)
        else:
            self.sinav_kurum_var.set("(Seçiniz)")

        # Puan
        self.sinav_puan_var.set(str(s["puan"]) if s["puan"] else "")

        # Dereceler
        derece_map = {
            "genel": s.get("genel_derece"),
            "il": s.get("il_derece"),
            "ilce": s.get("ilce_derece"),
            "kurum": s.get("kurum_derece"),
            "sube": s.get("sube_derece"),
        }
        for key, val in derece_map.items():
            if key in self.derece_vars:
                self.derece_vars[key].set(str(val) if val else "")

        # Dersler
        lgs_soru = {"Türkçe": 20, "Matematik": 20, "Fen": 20, "Sosyal": 10, "İngilizce": 10, "Din": 10}
        for ders in DERSLER:
            self.sinav_ders_vars[ders]["ss"].set(str(lgs_soru.get(ders, 10)))
            self.sinav_ders_vars[ders]["d"].set("0")
            self.sinav_ders_vars[ders]["y"].set("0")

        for d in detay["dersler"]:
            if d["ders"] in self.sinav_ders_vars:
                self.sinav_ders_vars[d["ders"]]["ss"].set(str(d["soru_sayisi"]))
                self.sinav_ders_vars[d["ders"]]["d"].set(str(d["dogru"]))
                self.sinav_ders_vars[d["ders"]]["y"].set(str(d["yanlis"]))

    def _sinav_sil(self):
        """Seçili sınavı sil."""
        sel = self.sinav_tablo.selection()
        if not sel:
            Messagebox.show_warning("Lütfen silmek istediğiniz sınavı seçin!", "Uyarı")
            return
        confirm = Messagebox.yesno("Seçili sınavı silmek istediğinize emin misiniz?", "Onay")
        if confirm == "Yes":
            sinav_id = int(self.sinav_tablo.item(sel[0], "values")[0])
            db.sinav_sil(sinav_id)
            self._sinav_listesini_guncelle()
            Messagebox.show_info("Sınav silindi!", "Başarılı")

    # ── Kurum combo güncellemeleri ──
    def _sinav_grafik_kurum_combo_guncelle(self):
        kurumlar = db.kurumlari_getir()
        self._kurum_listesi = kurumlar
        values = ["Tümü"] + [k["kurum_adi"] for k in kurumlar]
        self.sinav_grafik_kurum_combo.configure(values=values)

    def _sinav_liste_kurum_combo_guncelle(self):
        kurumlar = db.kurumlari_getir()
        self._kurum_listesi = kurumlar
        values = ["Tümü"] + [k["kurum_adi"] for k in kurumlar]
        self.sinav_liste_kurum_combo.configure(values=values)

    # ── Sınav Karşılaştırma Grafikleri ──
    def _get_kurum_id_by_name(self, kurum_adi):
        """Kurum adından ID bul."""
        if kurum_adi == "Tümü":
            return None
        for k in self._kurum_listesi:
            if k["kurum_adi"] == kurum_adi:
                return k["id"]
        return None

    def _sinav_grafik_guncelle(self):
        """Sınav karşılaştırma grafiklerini güncelle."""
        for widget in self.sinav_grafik_frame.winfo_children():
            widget.destroy()

        kurum_id = self._get_kurum_id_by_name(self.sinav_grafik_kurum_var.get())
        tip = self.sinav_grafik_tip_var.get()

        veriler = db.sinav_karsilastir(kurum_id)
        if not veriler:
            ttkb.Label(self.sinav_grafik_frame, text="Veri bulunamadı.",
                font=("Segoe UI", 12), bootstyle="secondary").pack(expand=True)
            return

        df = pd.DataFrame(veriler)

        fig = Figure(figsize=(10, 4), dpi=100)
        fig.patch.set_facecolor("#f8f9fa")

        if tip == "Puan Gelişimi (Line)":
            self._sinav_ciz_puan_line(fig, df)
        elif tip == "Net Gelişimi (Line)":
            self._sinav_ciz_net_line(fig, df)
        elif tip == "Derece Gelişimi (Line)":
            self._sinav_ciz_derece_line(fig, df)
        elif tip == "Ders Netleri Karşılaştırma (Bar)":
            self._sinav_ciz_ders_bar(fig, df)

        canvas = FigureCanvasTkAgg(fig, master=self.sinav_grafik_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=BOTH, expand=True)

        toolbar = NavigationToolbar2Tk(canvas, self.sinav_grafik_frame)
        toolbar.update()

    def _sinav_ciz_puan_line(self, fig, df):
        """Sınav puan gelişimi."""
        ax = fig.add_subplot(111)
        ax.set_facecolor("#ffffff")

        # Sınav bazında unique bilgi
        sinav_df = df.drop_duplicates(subset=["id"]).sort_values("sinav_tarihi")
        sinav_df = sinav_df[sinav_df["puan"].notna()]

        if sinav_df.empty:
            ax.text(0.5, 0.5, "Puan verisi bulunamadı", ha="center", va="center", fontsize=14)
            return

        # Kurum bazında grupla
        if sinav_df["kurum_adi"].nunique() > 1:
            for kurum, grp in sinav_df.groupby("kurum_adi"):
                lbl = kurum if kurum else "Belirtilmemiş"
                ax.plot(range(len(grp)), grp["puan"].values, marker="o", label=lbl, linewidth=2, markersize=6)
                for i, (_, row) in enumerate(grp.iterrows()):
                    ax.annotate(f"{row['puan']:.1f}", (i, row["puan"]),
                        textcoords="offset points", xytext=(0, 10), ha="center", fontsize=8, fontweight="bold")
        else:
            x_labels = [f"{r['sinav_adi']}\n{datetime.strptime(r['sinav_tarihi'],'%Y-%m-%d').strftime('%d.%m')}" for _, r in sinav_df.iterrows()]
            ax.plot(range(len(sinav_df)), sinav_df["puan"].values, marker="o",
                    color="#3498DB", linewidth=2.5, markersize=7)
            for i, (_, row) in enumerate(sinav_df.iterrows()):
                ax.annotate(f"{row['puan']:.1f}", (i, row["puan"]),
                    textcoords="offset points", xytext=(0, 10), ha="center",
                    fontsize=9, fontweight="bold", color="#2c3e50")
            ax.set_xticks(range(len(sinav_df)))
            ax.set_xticklabels(x_labels, fontsize=8, rotation=30, ha="right")

        ax.set_title("Sınav Puan Gelişimi", fontsize=14, fontweight="bold")
        ax.set_ylabel("Puan", fontsize=11)
        ax.grid(True, alpha=0.3)
        if sinav_df["kurum_adi"].nunique() > 1:
            ax.legend(fontsize=9)
        fig.tight_layout()

    def _sinav_ciz_net_line(self, fig, df):
        """Ders bazında net gelişimi."""
        ax = fig.add_subplot(111)
        ax.set_facecolor("#ffffff")

        sinav_ids = df.drop_duplicates(subset=["id"]).sort_values("sinav_tarihi")["id"].tolist()
        if not sinav_ids:
            ax.text(0.5, 0.5, "Veri bulunamadı", ha="center", va="center", fontsize=14)
            return

        sinav_labels = []
        for sid in sinav_ids:
            row = df[df["id"] == sid].iloc[0]
            tarih = datetime.strptime(row["sinav_tarihi"], "%Y-%m-%d").strftime("%d.%m")
            sinav_labels.append(f"{row['sinav_adi']}\n{tarih}")

        for ders in DERSLER:
            nets = []
            for sid in sinav_ids:
                ders_row = df[(df["id"] == sid) & (df["ders"] == ders)]
                nets.append(ders_row["net"].values[0] if not ders_row.empty else None)

            # Sadece veri olan noktaları çiz
            x_valid = [i for i, n in enumerate(nets) if pd.notna(n)]
            y_valid = [n for n in nets if pd.notna(n)]

            if y_valid:
                ax.plot(x_valid, y_valid, marker="o", label=ders,
                        color=DERS_RENKLERI[ders], linewidth=2, markersize=5)
                for x, y in zip(x_valid, y_valid):
                    ax.annotate(f"{y:.1f}", (x, y), textcoords="offset points",
                        xytext=(0, 8), ha="center", fontsize=7, fontweight="bold",
                        color=DERS_RENKLERI[ders])

        ax.set_xticks(range(len(sinav_ids)))
        ax.set_xticklabels(sinav_labels, fontsize=7, rotation=30, ha="right")
        ax.set_title("Ders Bazında Net Gelişimi", fontsize=14, fontweight="bold")
        ax.set_ylabel("Net", fontsize=11)
        ax.legend(fontsize=8, loc="best", ncol=2)
        ax.grid(True, alpha=0.3)
        fig.tight_layout()

    def _sinav_ciz_derece_line(self, fig, df):
        """Derece gelişimi - legend tıklanarak seri açılıp kapatılabilir."""
        ax = fig.add_subplot(111)
        ax.set_facecolor("#ffffff")

        sinav_df = df.drop_duplicates(subset=["id"]).sort_values("sinav_tarihi")

        x_labels = []
        for _, r in sinav_df.iterrows():
            tarih = datetime.strptime(r["sinav_tarihi"], "%Y-%m-%d").strftime("%d.%m")
            x_labels.append(f"{r['sinav_adi']}\n{tarih}")

        derece_types = [
            ("genel_derece", "Genel", "#E74C3C"),
            ("il_derece", "İl", "#3498DB"),
            ("ilce_derece", "İlçe", "#2ECC71"),
            ("kurum_derece", "Kurum", "#F39C12"),
            ("sube_derece", "Şube", "#9B59B6"),
        ]

        # Annotation çakışmasını önlemek için farklı y-offset
        y_offsets = [12, -16, 10, -14, 8]

        lines = []
        annotations_map = {}  # line -> [annotation list]

        for idx, (col, label, renk) in enumerate(derece_types):
            vals = sinav_df[col].tolist()
            x_valid = [i for i, v in enumerate(vals) if pd.notna(v)]
            y_valid = [v for v in vals if pd.notna(v)]
            if y_valid:
                line, = ax.plot(x_valid, y_valid, marker="o", label=label,
                        color=renk, linewidth=2, markersize=6)
                lines.append(line)

                y_off = y_offsets[idx % len(y_offsets)]
                anns = []
                for x, y in zip(x_valid, y_valid):
                    ann = ax.annotate(str(int(y)), (x, y), textcoords="offset points",
                        xytext=(0, y_off), ha="center", fontsize=8, fontweight="bold", color=renk)
                    anns.append(ann)
                annotations_map[line] = anns

        # Başlangıçta sadece Genel ve Şube görünsün (diğerleri gizli)
        gizlenecek = {"İl", "İlçe", "Kurum"}
        for line in lines:
            if line.get_label() in gizlenecek:
                line.set_visible(False)
                for ann in annotations_map.get(line, []):
                    ann.set_visible(False)

        ax.set_xticks(range(len(sinav_df)))
        ax.set_xticklabels(x_labels, fontsize=7, rotation=30, ha="right")
        ax.set_title("Derece Gelişimi  (legend'ı tıkla: aç/kapa)", fontsize=13, fontweight="bold")
        ax.set_ylabel("Derece (küçük=iyi)", fontsize=11)
        ax.invert_yaxis()

        leg = ax.legend(fontsize=9, loc="best")
        # Legend öğelerini renklendirip gizli olanları soluklaştır
        self._derece_line_map = {}  # legend_line -> (orig_line, annotations, renk)

        # Legend text ve çizgi renklerini doğru ayarla
        for leg_line, leg_text, orig_line in zip(leg.get_lines(), leg.get_texts(), lines):
            orig_renk = orig_line.get_color()
            leg_line.set_color(orig_renk)
            leg_line.set_linewidth(3)
            leg_line.set_picker(True)
            leg_line.set_pickradius(8)
            leg_text.set_color(orig_renk)
            self._derece_line_map[leg_line] = (orig_line, annotations_map.get(orig_line, []), orig_renk)
            if not orig_line.get_visible():
                leg_line.set_alpha(0.25)
                leg_text.set_alpha(0.4)

        ax.grid(True, alpha=0.3)
        fig.tight_layout()

        # Pick event bağla
        def on_pick(event):
            leg_line = event.artist
            if leg_line not in self._derece_line_map:
                return
            orig_line, anns, renk = self._derece_line_map[leg_line]
            vis = not orig_line.get_visible()
            orig_line.set_visible(vis)
            for ann in anns:
                ann.set_visible(vis)
            leg_line.set_alpha(1.0 if vis else 0.25)
            # Legend text'ini de güncelle
            for lt, ll in zip(leg.get_texts(), leg.get_lines()):
                if ll is leg_line:
                    lt.set_alpha(1.0 if vis else 0.4)
                    break
            fig.canvas.draw_idle()

        fig.canvas.mpl_connect("pick_event", on_pick)

    def _sinav_ciz_ders_bar(self, fig, df):
        """Sınavlar arası ders net karşılaştırma."""
        ax = fig.add_subplot(111)
        ax.set_facecolor("#ffffff")

        sinav_ids = df.drop_duplicates(subset=["id"]).sort_values("sinav_tarihi")["id"].tolist()
        if not sinav_ids:
            ax.text(0.5, 0.5, "Veri bulunamadı", ha="center", va="center", fontsize=14)
            return

        sinav_labels = []
        for sid in sinav_ids:
            row = df[df["id"] == sid].iloc[0]
            tarih = datetime.strptime(row["sinav_tarihi"], "%Y-%m-%d").strftime("%d.%m")
            sinav_labels.append(f"{row['sinav_adi']}\n{tarih}")

        x = np.arange(len(sinav_ids))
        bar_w = 0.12
        n_ders = len(DERSLER)

        for i, ders in enumerate(DERSLER):
            nets = []
            for sid in sinav_ids:
                ders_row = df[(df["id"] == sid) & (df["ders"] == ders)]
                nets.append(ders_row["net"].values[0] if not ders_row.empty else 0)

            bars = ax.bar(x + i * bar_w - (n_ders * bar_w) / 2, nets, bar_w,
                    label=ders, color=DERS_RENKLERI[ders])
            for bar, val in zip(bars, nets):
                if val > 0:
                    ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.1,
                            f"{val:.1f}", ha="center", fontsize=6, fontweight="bold")

        ax.set_xticks(x)
        ax.set_xticklabels(sinav_labels, fontsize=7, rotation=30, ha="right")
        ax.set_title("Sınavlar Arası Ders Net Karşılaştırması", fontsize=14, fontweight="bold")
        ax.set_ylabel("Net", fontsize=11)
        ax.legend(fontsize=8, loc="best", ncol=2)
        ax.grid(True, axis="y", alpha=0.3)
        fig.tight_layout()

    # =====================================================
    # SEKME 6: AI ANALİZ
    # =====================================================
    def _build_ai_tab(self):
        """AI destekli analiz sekmesi."""
        tab = ttkb.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="  🤖 AI Analiz  ")

        # Üst kontrol paneli
        kontrol_frame = ttkb.Labelframe(tab, text="AI Analiz Kontrolleri", padding=10, bootstyle="primary")
        kontrol_frame.pack(fill=X, pady=(0, 10))

        left_ctrl = ttkb.Frame(kontrol_frame)
        left_ctrl.pack(side=LEFT, fill=X, expand=True)

        ttkb.Label(left_ctrl, text="Analiz Dönemi:", font=("Segoe UI", 10)).pack(side=LEFT, padx=5)
        self.ai_donem_var = tk.StringVar(value="90")
        ttkb.Combobox(
            left_ctrl,
            textvariable=self.ai_donem_var,
            values=["30", "60", "90", "180"],
            state="readonly",
            width=8,
            font=("Segoe UI", 10),
        ).pack(side=LEFT, padx=5)
        ttkb.Label(left_ctrl, text="gün", font=("Segoe UI", 10)).pack(side=LEFT)

        ttkb.Label(left_ctrl, text="   |   Analiz Türü:", font=("Segoe UI", 10)).pack(side=LEFT, padx=5)
        self.ai_tur_var = tk.StringVar(value="Kapsamlı Analiz")
        ttkb.Combobox(
            left_ctrl,
            textvariable=self.ai_tur_var,
            values=["Kapsamlı Analiz", "Haftalık Çalışma Planı", "Zayıf Noktalar & Odak", "Motivasyon & Tavsiye"],
            state="readonly",
            width=25,
            font=("Segoe UI", 10),
        ).pack(side=LEFT, padx=5)

        # Butonlar
        btn_frame = ttkb.Frame(kontrol_frame)
        btn_frame.pack(side=RIGHT)

        self.ai_analiz_btn = ttkb.Button(
            btn_frame,
            text="🤖 AI Analiz Yap",
            command=self._ai_analiz_baslat,
            bootstyle="success",
            width=18,
        )
        self.ai_analiz_btn.pack(side=LEFT, padx=5)

        ttkb.Button(
            btn_frame,
            text="🔑 API Ayarları",
            command=self._api_key_dialog,
            bootstyle="info-outline",
            width=14,
        ).pack(side=LEFT, padx=5)

        # Durum çubuğu
        self.ai_durum_frame = ttkb.Frame(tab)
        self.ai_durum_frame.pack(fill=X, pady=(0, 5))

        self.ai_durum_label = ttkb.Label(
            self.ai_durum_frame,
            text="💡 AI analiz için yukarıdaki butona tıklayın. İlk kullanımda Ayarlar → API Anahtarı gerekir.",
            font=("Segoe UI", 9),
            bootstyle="secondary",
        )
        self.ai_durum_label.pack(side=LEFT)

        # AI yanıt alanı
        sonuc_frame = ttkb.Labelframe(tab, text="🤖 AI Analiz Sonucu", padding=10, bootstyle="info")
        sonuc_frame.pack(fill=BOTH, expand=True)

        self.ai_text = tk.Text(
            sonuc_frame,
            wrap=tk.WORD,
            font=("Segoe UI", 10),
            bg="#f0f4f8",
            fg="#2c3e50",
            relief=tk.FLAT,
            padx=15,
            pady=15,
            spacing1=2,
            spacing2=2,
            spacing3=4,
        )
        ai_scroll = ttkb.Scrollbar(sonuc_frame, orient=VERTICAL, command=self.ai_text.yview)
        self.ai_text.configure(yscrollcommand=ai_scroll.set)
        self.ai_text.pack(side=LEFT, fill=BOTH, expand=True)
        ai_scroll.pack(side=RIGHT, fill=Y)

        # Text tag'leri
        self.ai_text.tag_configure("ai_baslik", font=("Segoe UI", 14, "bold"), foreground="#1a5276",
                                   spacing3=6)
        self.ai_text.tag_configure("ai_alt_baslik", font=("Segoe UI", 11, "bold"), foreground="#2e86c1",
                                   spacing1=8, spacing3=4)
        self.ai_text.tag_configure("ai_normal", font=("Segoe UI", 10), foreground="#2c3e50")
        self.ai_text.tag_configure("ai_vurgu", font=("Segoe UI", 10, "bold"), foreground="#117a65")
        self.ai_text.tag_configure("ai_uyari", font=("Segoe UI", 10, "bold"), foreground="#e74c3c")
        self.ai_text.tag_configure("ai_oneri", font=("Segoe UI", 10), foreground="#6c3483")
        self.ai_text.tag_configure("ai_emoji", font=("Segoe UI", 10))
        self.ai_text.tag_configure("ai_ayrac", foreground="#bdc3c7", font=("Segoe UI", 8))
        self.ai_text.tag_configure("ai_meta", font=("Segoe UI", 8), foreground="#95a5a6")

        # Başlangıç mesajı
        self._ai_goster_hosgeldiniz()

    def _ai_goster_hosgeldiniz(self):
        """AI sekmesi başlangıç mesajı."""
        self.ai_text.configure(state=tk.NORMAL)
        self.ai_text.delete("1.0", tk.END)
        self.ai_text.insert(tk.END, "🤖 AI Destekli Performans Analizi\n", "ai_baslik")
        self.ai_text.insert(tk.END, "━" * 50 + "\n\n", "ai_ayrac")
        self.ai_text.insert(tk.END, "Bu özellik, yapay zeka modellerini kullanarak\n", "ai_normal")
        self.ai_text.insert(tk.END, "soru çözüm verilerinizi analiz eder ve kişiye özel öneriler sunar.\n\n", "ai_normal")
        self.ai_text.insert(tk.END, "📌 Desteklenen AI Sağlayıcılar:\n", "ai_alt_baslik")
        self.ai_text.insert(tk.END, "  🌟 Google Gemini — Ücretsiz API kotası mevcut (aistudio.google.com)\n", "ai_normal")
        self.ai_text.insert(tk.END, "  💠 OpenAI (ChatGPT) — Çok ucuz ~$0.003/analiz (platform.openai.com)\n\n", "ai_normal")
        self.ai_text.insert(tk.END, "📌 Nasıl Çalışır?\n", "ai_alt_baslik")
        self.ai_text.insert(tk.END, "  1. Performans verileriniz özetlenerek AI'ya gönderilir\n", "ai_normal")
        self.ai_text.insert(tk.END, "  2. Kişisel bilgi gönderilmez — sadece soru/doğru/yanlış istatistikleri\n", "ai_normal")
        self.ai_text.insert(tk.END, "  3. AI, güçlü/zayıf yönlerinizi analiz eder\n", "ai_normal")
        self.ai_text.insert(tk.END, "  4. Kişiye özel çalışma planı ve motivasyon önerileri sunar\n\n", "ai_normal")
        self.ai_text.insert(tk.END, "🔑 Başlamak İçin:\n", "ai_alt_baslik")

        provider = db.oku_ayar("ai_provider", "gemini")
        api_key = db.oku_ayar(f"{provider}_api_key", "")
        if api_key:
            prov_name = "Gemini" if provider == "gemini" else "OpenAI"
            self.ai_text.insert(tk.END, f"  ✅ {prov_name} API anahtarı kayıtlı. ", "ai_vurgu")
            self.ai_text.insert(tk.END, "\"🤖 AI Analiz Yap\" butonuna tıklayın.\n", "ai_normal")
        else:
            self.ai_text.insert(tk.END, "  ⚠️ Önce API anahtarı girilmeli.\n", "ai_uyari")
            self.ai_text.insert(tk.END, "  Ayarlar → AI API Ayarları menüsünden anahtarınızı girin.\n", "ai_normal")
        self.ai_text.configure(state=tk.DISABLED)

    def _ai_analiz_baslat(self):
        """AI analizi başlat (thread ile)."""
        provider = db.oku_ayar("ai_provider", "gemini")
        api_key = db.oku_ayar(f"{provider}_api_key", "")
        if not api_key:
            prov_name = "Gemini" if provider == "gemini" else "OpenAI"
            messagebox.showwarning(
                "API Anahtarı Gerekli",
                f"AI analiz için {prov_name} API anahtarı gereklidir.\n\n"
                "Ayarlar → AI API Ayarları menüsünden anahtarınızı girin."
            )
            return

        # Butonu devre dışı bırak
        self.ai_analiz_btn.configure(state=tk.DISABLED, text="⏳ Analiz Ediliyor...")
        self.ai_durum_label.configure(text="⏳ AI modeli çalışıyor, lütfen bekleyin...", bootstyle="warning")

        # Yanıt alanını temizle
        self.ai_text.configure(state=tk.NORMAL)
        self.ai_text.delete("1.0", tk.END)
        self.ai_text.insert(tk.END, "⏳ AI analiz hazırlanıyor...\n\n", "ai_baslik")
        self.ai_text.insert(tk.END, "Veriler toplanıyor ve yapay zekaya gönderiliyor.\n", "ai_normal")
        self.ai_text.insert(tk.END, "Bu işlem birkaç saniye sürebilir...\n", "ai_meta")
        self.ai_text.configure(state=tk.DISABLED)

        # Thread ile API çağrısı
        thread = threading.Thread(target=self._ai_analiz_calistir, daemon=True)
        thread.start()

    def _ai_prompt_olustur(self, veri: dict) -> str:
        """AI için Türkçe prompt oluştur."""
        donem = veri["son_gun"]
        tur = self.ai_tur_var.get()

        prompt = f"""Sen bir LGS (Liseye Geçiş Sınavı) eğitim koçusun. Bir 8. sınıf öğrencisinin son {donem} günlük çalışma verilerini analiz edeceksin.

## LGS Hakkında Bilgiler:
- LGS 6 dersten oluşur: Türkçe (20 soru), Matematik (20 soru), Fen Bilimleri (20 soru), Sosyal Bilgiler (10 soru), İngilizce (10 soru), Din Kültürü (10 soru)
- Toplam 90 soru, 3 yanlış 1 doğruyu götürür (sınavda)
- Günlük çalışmada 4 yanlış 1 doğruyu götürür (net hesaplama)
- 500 puan üzeri çok iyi, 450+ iyi, 400+ orta, 400 altı geliştirilmeli

## Öğrencinin Performans Verileri (Son {donem} Gün):
"""
        # Genel istatistik
        genel = veri.get("genel", {})
        if genel:
            prompt += f"""
### Genel Özet:
- Toplam çalışılan gün: {genel.get('toplam_gun', 0)}
- Toplam çözülen soru: {genel.get('toplam_soru', 0)}
- Toplam doğru: {genel.get('toplam_dogru', 0)} | Toplam yanlış: {genel.get('toplam_yanlis', 0)}
- Toplam net: {genel.get('toplam_net', 0)}
- Genel başarı oranı: %{genel.get('genel_basari', 0)}
"""
        else:
            prompt += "\n### Genel Özet: Henüz veri yok.\n"

        # Ders bazında detay
        prompt += "\n### Ders Bazında Performans:\n"
        dersler = veri.get("dersler", {})
        if dersler:
            for ders_adi, d in dersler.items():
                prompt += f"""
**{ders_adi}:**
- Toplam soru: {d['toplam_soru']} | Doğru: {d['toplam_dogru']} | Yanlış: {d['toplam_yanlis']} | Net: {d['toplam_net']}
- Çalışılan gün: {d['gun_sayisi']} | Günlük ort. soru: {d['gunluk_ort_soru']}
- Genel başarı: %{d['basari_yuzdesi']}
- Son 7 gün başarısı: %{d['son7_basari']} | Önceki 7 gün: %{d['onceki7_basari']}
"""
        else:
            prompt += "Henüz ders verisi yok.\n"

        # Sınav sonuçları
        sinavlar = veri.get("sinavlar", [])
        if sinavlar:
            prompt += "\n### Son Sınav Sonuçları:\n"
            for s in sinavlar:
                puan_str = f"Puan: {s['puan']}" if s.get('puan') else "Puan: -"
                derece_str = f"Genel Derece: {s.get('genel_derece', '-')}, İl Derece: {s.get('il_derece', '-')}"
                prompt += f"- **{s['sinav_adi']}** ({s['sinav_tarihi']}): {puan_str} | {derece_str}\n"
                if s.get("dersler"):
                    for dd in s["dersler"]:
                        prompt += f"  → {dd['ders']}: D:{dd['dogru']} Y:{dd['yanlis']} Net:{dd['net']}\n"

        # Analiz türüne göre talep
        prompt += "\n## İstenen Analiz:\n"

        if tur == "Kapsamlı Analiz":
            prompt += """
Lütfen aşağıdaki başlıklarda detaylı Türkçe analiz yap:

1. **📊 GENEL PERFORMANS DEĞERLENDİRMESİ**
   - Öğrencinin genel durumu, güçlü ve zayıf yönleri

2. **📈 DERS BAZINDA ANALİZ**
   - Her ders için ayrı değerlendirme
   - Trend analizi (yükselen/düşen performans)
   - Dikkat edilmesi gereken noktalar

3. **⚠️ KRİTİK UYARILAR**
   - Acil müdahale gerektiren dersler/konular
   - Düşüş eğilimi gösteren alanlar

4. **🎯 HEDEF ve PLAN**
   - Günlük çalışma planı önerisi (saat bazlı)
   - Haftalık ders dağılımı
   - Öncelik sıralaması

5. **💪 MOTİVASYON**
   - Pozitif geri bildirim
   - Küçük hedefler ve ödül sistemi önerisi
"""
        elif tur == "Haftalık Çalışma Planı":
            prompt += """
Öğrencinin verilerine göre detaylı bir HAFTALIK ÇALIŞMA PLANI oluştur:
- Pazartesi'den Pazar'a her gün için ders programı
- Her ders için önerilen soru sayısı
- Zayıf derslere daha fazla zaman ayır
- Tekrar günleri bırak
- Motivasyon önerileri ekle
- Saat bazlı plan öner (okul saatleri dışında)
"""
        elif tur == "Zayıf Noktalar & Odak":
            prompt += """
Sadece öğrencinin ZAYIF NOKTALARINA odaklan:
- En düşük başarılı dersler ve nedenleri
- Düşüş eğilimi gösteren dersler
- Az çalışılan dersler
- Her zayıf alan için spesifik iyileştirme stratejisi
- Konu bazlı öneriler (LGS müfredatına göre)
- Acil eylem planı (önümüzdeki 2 hafta)
"""
        elif tur == "Motivasyon & Tavsiye":
            prompt += """
Öğrenciyi motive edecek bir mesaj yaz:
- Başarılı olduğu alanları vurgula
- İlerlemeyi göster
- LGS başarı hikayeleri ve ilham verici mesajlar
- Stres yönetimi önerileri
- Küçük adımlarla büyük başarı stratejisi
- Pozitif ve enerjik bir ton kullan
"""

        prompt += """
⚠️ Önemli kurallar:
- Tamamen Türkçe yaz
- Emoji kullan, okumayı kolaylaştır
- Somut ve uygulanabilir öneriler ver
- 8. sınıf öğrencisinin anlayacağı dilde yaz
- Net sayılar ve yüzdeler kullan
- Paragrafları kısa tut
"""
        return prompt

    def _ai_analiz_calistir(self):
        """API çağrısını arka planda çalıştır."""
        try:
            provider = db.oku_ayar("ai_provider", "gemini")
            api_key = db.oku_ayar(f"{provider}_api_key", "")
            son_gun = int(self.ai_donem_var.get())

            # Veri topla
            veri = db.ai_analiz_verisi(son_gun)

            if not veri.get("dersler") and not veri.get("sinavlar"):
                self.root.after(0, self._ai_sonuc_goster, 
                    "📭 Analiz için yeterli veri bulunamadı.\n\n"
                    "Lütfen önce 'Veri Girişi' sekmesinden soru çözüm kayıtları ekleyin.",
                    False)
                return

            # Prompt oluştur
            prompt = self._ai_prompt_olustur(veri)

            if provider == "openai":
                yanit = self._openai_cagir(api_key, prompt)
            else:
                yanit = self._gemini_cagir(api_key, prompt)

            # Ana thread'de göster
            self.root.after(0, self._ai_sonuc_goster, yanit, True)

        except Exception as e:
            hata_mesaji = str(e)
            if "API_KEY" in hata_mesaji.upper() or "INVALID" in hata_mesaji.upper() \
               or "401" in hata_mesaji or "Incorrect API key" in hata_mesaji \
               or "authentication" in hata_mesaji.lower():
                hata = (
                    "❌ API Anahtarı Hatası\n\n"
                    "API anahtarınız geçersiz veya süresi dolmuş olabilir.\n"
                    "Ayarlar → AI API Ayarları menüsünden kontrol edin.\n\n"
                    f"Detay: {hata_mesaji}"
                )
            elif "QUOTA" in hata_mesaji.upper() or "429" in hata_mesaji \
                 or "rate" in hata_mesaji.lower() or "exceeded" in hata_mesaji.lower():
                hata = (
                    "⚠️ API Kotası Aşıldı\n\n"
                    "API kotanız dolmuş olabilir.\n"
                    "Birkaç dakika bekleyip tekrar deneyin veya\n"
                    "Ayarlar'dan diğer sağlayıcıya geçin (Gemini ↔ OpenAI).\n\n"
                    f"Detay: {hata_mesaji}"
                )
            elif "SAFETY" in hata_mesaji.upper():
                hata = (
                    "⚠️ İçerik Filtresi\n\n"
                    "AI güvenlik filtresi yanıtı engelledi.\n"
                    "Farklı bir analiz türü deneyin.\n\n"
                    f"Detay: {hata_mesaji}"
                )
            else:
                hata = (
                    f"❌ AI Analiz Hatası\n\n"
                    f"Bir hata oluştu: {hata_mesaji}\n\n"
                    "İnternet bağlantınızı kontrol edin ve tekrar deneyin."
                )
            self.root.after(0, self._ai_sonuc_goster, hata, False)

    def _gemini_model_adi(self) -> str:
        """Kayıtlı Gemini modelini döndür; boş veya artık kullanılmayan adları günceller."""
        model = (db.oku_ayar("ai_model", "") or "").strip()
        if (not model
                or model in ("gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro",
                             "gemini-pro", "gemini-1.0-pro", "gemini-2.0-flash-exp")
                or model.startswith("gemini-1.")
                or model.startswith("gemini-2.0")):
            return DEFAULT_GEMINI_MODEL
        return model

    def _gemini_cagir(self, api_key: str, prompt: str) -> str:
        """Google Gemini API çağrısı."""
        import google.generativeai as genai

        genai.configure(api_key=api_key)

        model_adi = self._gemini_model_adi()
        model = genai.GenerativeModel(model_adi)

        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.7,
                max_output_tokens=4096,
            ),
            request_options={"timeout": 120},
        )
        return self._gemini_response_to_text(response) or "AI yanıt üretemedi."

    def _openai_cagir(self, api_key: str, prompt: str) -> str:
        """OpenAI API çağrısı."""
        from openai import OpenAI

        client = OpenAI(api_key=api_key)

        model_adi = db.oku_ayar("ai_model", "") or "gpt-4o-mini"

        response = client.chat.completions.create(
            model=model_adi,
            messages=[
                {"role": "system", "content": "Sen bir LGS eğitim koçusun. Türkçe konuş, emoji kullan, 8. sınıf öğrencisine hitap et."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=4096,
        )
        return response.choices[0].message.content or "AI yanıt üretemedi."

    def _ai_sonuc_goster(self, yanit: str, basarili: bool):
        """AI sonucunu Text widget'ta göster."""
        self.ai_analiz_btn.configure(state=tk.NORMAL, text="🤖 AI Analiz Yap")

        self.ai_text.configure(state=tk.NORMAL)
        self.ai_text.delete("1.0", tk.END)

        if basarili:
            self.ai_durum_label.configure(
                text=f"✅ Analiz tamamlandı — {datetime.now().strftime('%H:%M:%S')}",
                bootstyle="success"
            )

            # Markdown benzeri formatlama
            self._ai_markdown_render(yanit)
        else:
            self.ai_durum_label.configure(text="❌ Analiz başarısız", bootstyle="danger")
            self.ai_text.insert(tk.END, yanit, "ai_normal")

        self.ai_text.configure(state=tk.DISABLED)

    def _ai_markdown_render(self, text: str):
        """Basit markdown render — başlıklar, kalın, emoji destekli."""
        lines = text.split("\n")
        for line in lines:
            stripped = line.strip()

            # Başlıklar
            if stripped.startswith("### "):
                self.ai_text.insert(tk.END, stripped[4:] + "\n", "ai_alt_baslik")
            elif stripped.startswith("## "):
                self.ai_text.insert(tk.END, stripped[3:] + "\n", "ai_baslik")
            elif stripped.startswith("# "):
                self.ai_text.insert(tk.END, stripped[2:] + "\n", "ai_baslik")
            elif stripped.startswith("---") or stripped.startswith("━"):
                self.ai_text.insert(tk.END, "━" * 50 + "\n", "ai_ayrac")
            elif stripped.startswith("⚠") or stripped.startswith("❌") or stripped.startswith("🔴"):
                self.ai_text.insert(tk.END, line + "\n", "ai_uyari")
            elif stripped.startswith("✅") or stripped.startswith("🟢") or stripped.startswith("💪"):
                self.ai_text.insert(tk.END, line + "\n", "ai_vurgu")
            elif stripped.startswith("**") and stripped.endswith("**"):
                # Kalın satır
                self.ai_text.insert(tk.END, stripped[2:-2] + "\n", "ai_alt_baslik")
            else:
                # Satır içi **kalın** ayrıştırma
                self._ai_render_inline(line + "\n")

    def _ai_render_inline(self, text: str):
        """Satır içi **kalın** metin render."""
        parts = text.split("**")
        for i, part in enumerate(parts):
            if i % 2 == 1:
                # Kalın
                self.ai_text.insert(tk.END, part, "ai_vurgu")
            else:
                self.ai_text.insert(tk.END, part, "ai_normal")

    # =====================================================
    # SEKME 7: KARNE ANALİZİ (PDF)
    # =====================================================
    def _build_karne_tab(self):
        """PDF Karne analizi sekmesi."""
        tab = ttkb.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="  📋 Karne Analizi  ")

        # ── Üst kontrol paneli ──
        kontrol_frame = ttkb.Labelframe(tab, text="PDF Karne Yönetimi", padding=10, bootstyle="primary")
        kontrol_frame.pack(fill=X, pady=(0, 8))

        left_ctrl = ttkb.Frame(kontrol_frame)
        left_ctrl.pack(side=LEFT, fill=X, expand=True)

        ttkb.Button(
            left_ctrl, text="📄 PDF Yükle", command=self._karne_pdf_yukle,
            bootstyle="success", width=14,
        ).pack(side=LEFT, padx=5)

        ttkb.Button(
            left_ctrl, text="🗑️ Seçili Sil", command=self._karne_sil,
            bootstyle="danger-outline", width=12,
        ).pack(side=LEFT, padx=5)

        ttkb.Separator(left_ctrl, orient=VERTICAL, bootstyle="secondary").pack(side=LEFT, fill=Y, padx=10)

        ttkb.Label(left_ctrl, text="Dönem:", font=("Segoe UI", 10)).pack(side=LEFT, padx=5)
        self.karne_donem_var = tk.StringVar(value="Tümü")
        ttkb.Combobox(
            left_ctrl, textvariable=self.karne_donem_var,
            values=["Son 7 Gün", "Son 14 Gün", "Son 30 Gün", "Son 90 Gün", "Tümü"],
            state="readonly", width=12, font=("Segoe UI", 10),
        ).pack(side=LEFT, padx=5)

        ttkb.Label(left_ctrl, text="Ders:", font=("Segoe UI", 10)).pack(side=LEFT, padx=5)
        self.karne_ders_var = tk.StringVar(value="Tümü")
        ttkb.Combobox(
            left_ctrl, textvariable=self.karne_ders_var,
            values=["Tümü"] + DERSLER,
            state="readonly", width=12, font=("Segoe UI", 10),
        ).pack(side=LEFT, padx=5)

        ttkb.Button(
            left_ctrl, text="📊 Analiz Et", command=self._karne_analiz_goster,
            bootstyle="info", width=12,
        ).pack(side=LEFT, padx=10)

        # ── Ana içerik: sol (karneler listesi) + sağ (analiz) ──
        paned = ttkb.Panedwindow(tab, orient=tk.HORIZONTAL)
        paned.pack(fill=BOTH, expand=True)

        # SOL: Yüklü karneler listesi
        sol_frame = ttkb.Labelframe(paned, text="📄 Yüklü Karneler", padding=5, bootstyle="secondary")
        paned.add(sol_frame, weight=1)

        # Karne listesi Treeview
        cols = ("tarih", "sinav", "kurum", "dosya")
        self.karne_tree = ttkb.Treeview(sol_frame, columns=cols, show="headings", height=8,
                                         selectmode="extended")
        self.karne_tree.heading("tarih", text="Tarih")
        self.karne_tree.heading("sinav", text="Sınav")
        self.karne_tree.heading("kurum", text="Kurum")
        self.karne_tree.heading("dosya", text="Dosya")
        self.karne_tree.column("tarih", width=80, minwidth=70)
        self.karne_tree.column("sinav", width=140, minwidth=100)
        self.karne_tree.column("kurum", width=100, minwidth=80)
        self.karne_tree.column("dosya", width=120, minwidth=80)

        karne_scroll = ttkb.Scrollbar(sol_frame, orient=VERTICAL, command=self.karne_tree.yview)
        self.karne_tree.configure(yscrollcommand=karne_scroll.set)
        self.karne_tree.pack(side=LEFT, fill=BOTH, expand=True)
        karne_scroll.pack(side=RIGHT, fill=Y)

        self.karne_tree.bind("<<TreeviewSelect>>", self._karne_secim_degisti)

        # SAĞ: Analiz sonuçları
        sag_frame = ttkb.Frame(paned)
        paned.add(sag_frame, weight=3)

        # Sağ taraf notebook (alt sekmeler)
        self.karne_notebook = ttkb.Notebook(sag_frame, bootstyle="info")
        self.karne_notebook.pack(fill=BOTH, expand=True)

        # Alt sekme 1: Konu Hata Raporu
        self.karne_konu_frame = ttkb.Frame(self.karne_notebook, padding=5)
        self.karne_notebook.add(self.karne_konu_frame, text="  ❌ Konu Hata Raporu  ")

        # Alt sekme 2: Ders Özet
        self.karne_ders_frame = ttkb.Frame(self.karne_notebook, padding=5)
        self.karne_notebook.add(self.karne_ders_frame, text="  📊 Ders Özet  ")

        # Alt sekme 3: Gelişim Raporu
        self.karne_gelisim_frame = ttkb.Frame(self.karne_notebook, padding=5)
        self.karne_notebook.add(self.karne_gelisim_frame, text="  📈 Gelişim Raporu  ")

        # Alt sekme 4: Detay
        self.karne_detay_frame = ttkb.Frame(self.karne_notebook, padding=5)
        self.karne_notebook.add(self.karne_detay_frame, text="  📝 Karne Detay  ")

        # Alt sekme 5: Bilgi Bankası (RAG)
        self.karne_rag_frame = ttkb.Frame(self.karne_notebook, padding=5)
        self.karne_notebook.add(self.karne_rag_frame, text="  🔍 Bilgi Bankası  ")
        self._build_rag_tab()

        # Karne listesini yükle
        self._karne_listesi_guncelle()

    def _karne_donem_gun(self) -> int:
        """Seçili dönem filtresi için gün sayısını döndür."""
        donem_map = {
            "Son 7 Gün": 7, "Son 14 Gün": 14, "Son 30 Gün": 30, "Son 90 Gün": 90, "Tümü": None,
        }
        return donem_map.get(self.karne_donem_var.get())

    def _karne_listesi_guncelle(self):
        """Karne listesini yenile."""
        for item in self.karne_tree.get_children():
            self.karne_tree.delete(item)

        karneler = db.karneleri_getir(self._karne_donem_gun())
        for k in karneler:
            tarih = k["sinav_tarihi"]
            try:
                tarih = datetime.strptime(tarih, "%Y-%m-%d").strftime("%d.%m.%Y")
            except Exception:
                pass
            self.karne_tree.insert("", tk.END, iid=str(k["id"]),
                values=(tarih, k.get("sinav_adi", ""), k.get("kurum_adi", ""), k["dosya_adi"]))

    def _karne_pdf_yukle(self):
        """PDF dosyası seç ve AI ile analiz et."""
        dosyalar = filedialog.askopenfilenames(
            title="PDF Karne Seç",
            filetypes=[("PDF Dosyaları", "*.pdf"), ("Tüm Dosyalar", "*.*")],
            initialdir=os.path.join(os.path.dirname(db.DB_PATH), "PDFS") if os.path.isdir(
                os.path.join(os.path.dirname(db.DB_PATH), "PDFS")) else None,
        )
        if not dosyalar:
            return

        # API kontrolü
        provider = db.oku_ayar("ai_provider", "gemini")
        api_key = db.oku_ayar(f"{provider}_api_key", "")
        if not api_key:
            messagebox.showwarning(
                "API Anahtarı Gerekli",
                "Karne analizi için AI API anahtarı gereklidir.\n\n"
                "Ayarlar → AI API Ayarları menüsünden anahtarınızı girin."
            )
            return

        # Tek tek işle
        for dosya in dosyalar:
            self._karne_tek_pdf_isle(dosya, provider, api_key)

    def _karne_tek_pdf_isle(self, dosya_yolu: str, provider: str, api_key: str):
        """Tek bir PDF'i işle: metin çıkar → AI analiz → DB kaydet."""
        dosya_adi = os.path.basename(dosya_yolu)

        # PDF'den metin çıkar
        raw_text = ""
        try:
            with pdfplumber.open(dosya_yolu) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        raw_text += page_text + "\n\n"

                    # Tabloları da çıkar
                    tables = page.extract_tables()
                    for table in tables:
                        for row in table:
                            if row:
                                cleaned = [str(cell).strip() if cell else "" for cell in row]
                                raw_text += " | ".join(cleaned) + "\n"
                        raw_text += "\n"
        except Exception as e:
            messagebox.showerror("PDF Hatası", f"PDF okunamadı:\n{dosya_adi}\n\n{str(e)}")
            return

        if not raw_text.strip():
            messagebox.showwarning("Uyarı", f"PDF'den metin çıkarılamadı:\n{dosya_adi}")
            return

        # Tarih dialog
        tarih_dialog = self._karne_tarih_sor(dosya_adi)
        if not tarih_dialog:
            return

        sinav_tarihi, kurum_adi, sinav_adi = tarih_dialog

        # Progress göster
        progress_win = tk.Toplevel(self.root)
        progress_win.title("⏳ Karne Analiz Ediliyor...")
        progress_win.geometry("420x130")
        progress_win.resizable(False, False)
        progress_win.transient(self.root)
        progress_win.grab_set()
        progress_win.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - 420) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 130) // 2
        progress_win.geometry(f"+{x}+{y}")

        pf = ttkb.Frame(progress_win, padding=20)
        pf.pack(fill=BOTH, expand=True)
        ttkb.Label(pf, text=f"📄 {dosya_adi}", font=("Segoe UI", 10, "bold")).pack()
        ttkb.Label(pf, text="AI analiz ediyor, lütfen bekleyin...", font=("Segoe UI", 9),
                   bootstyle="secondary").pack(pady=5)
        progress_bar = ttkb.Progressbar(pf, mode="indeterminate", bootstyle="info")
        progress_bar.pack(fill=X, pady=5)
        progress_bar.start(15)
        progress_win.update()

        def islem():
            try:
                sonuc = self._karne_ai_analiz(raw_text, provider, api_key)
                # AI hiç ders/konu çıkaramadıysa boş kayıt oluşturma, kullanıcıyı bilgilendir.
                if not sonuc.get("dersler") and not sonuc.get("konular"):
                    self.root.after(0, lambda: self._karne_bos_sonuc(
                        dosya_adi, raw_text, sonuc, progress_win))
                    return
                # RAG: chunk + embed (opsiyonel, hata durumunda atla)
                rag_data = None
                try:
                    chunks = self._rag_chunk_text(raw_text)
                    embeddings = self._rag_embed_chunks(chunks, provider, api_key)
                    if embeddings:
                        rag_data = (chunks, embeddings, provider)
                except Exception:
                    pass  # Embedding hatası karne kaydını engellemez
                self.root.after(0, lambda: self._karne_kaydet(
                    dosya_adi, sinav_tarihi, kurum_adi, sinav_adi, raw_text, sonuc, rag_data, progress_win))
            except Exception as e:
                self.root.after(0, lambda: self._karne_hata(str(e), progress_win))

        thread = threading.Thread(target=islem, daemon=True)
        thread.start()

    def _karne_tarih_sor(self, dosya_adi: str):
        """Karne tarihi ve bilgilerini sor."""
        dialog = tk.Toplevel(self.root)
        dialog.title("📄 Karne Bilgileri")
        dialog.geometry("440x320")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - 440) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 320) // 2
        dialog.geometry(f"+{x}+{y}")

        frame = ttkb.Frame(dialog, padding=20)
        frame.pack(fill=BOTH, expand=True)

        ttkb.Label(frame, text="📄 Karne Bilgilerini Girin",
                   font=("Segoe UI", 12, "bold"), bootstyle="primary").pack(anchor=W, pady=(0, 5))

        ttkb.Label(frame, text=f"Dosya: {dosya_adi}",
                   font=("Segoe UI", 9), bootstyle="secondary").pack(anchor=W, pady=(0, 10))

        ttkb.Separator(frame, bootstyle="secondary").pack(fill=X, pady=(0, 10))

        # Grid layout for cleaner form
        form = ttkb.Frame(frame)
        form.pack(fill=X)

        ttkb.Label(form, text="Sınav Tarihi:", font=("Segoe UI", 10)).grid(row=0, column=0, sticky=W, pady=5)
        tarih_var = tk.StringVar(value=datetime.now().strftime("%d.%m.%Y"))
        ttkb.Entry(form, textvariable=tarih_var, font=("Segoe UI", 10), width=18).grid(row=0, column=1, sticky=W, padx=(10, 0), pady=5)
        ttkb.Label(form, text="GG.AA.YYYY", font=("Segoe UI", 8), bootstyle="secondary").grid(row=0, column=2, sticky=W, padx=5, pady=5)

        ttkb.Label(form, text="Kurum Adı:", font=("Segoe UI", 10)).grid(row=1, column=0, sticky=W, pady=5)
        kurum_var = tk.StringVar()
        ttkb.Entry(form, textvariable=kurum_var, font=("Segoe UI", 10), width=28).grid(row=1, column=1, columnspan=2, sticky=W, padx=(10, 0), pady=5)

        ttkb.Label(form, text="Sınav Adı:", font=("Segoe UI", 10)).grid(row=2, column=0, sticky=W, pady=5)
        sinav_var = tk.StringVar()
        ttkb.Entry(form, textvariable=sinav_var, font=("Segoe UI", 10), width=28).grid(row=2, column=1, columnspan=2, sticky=W, padx=(10, 0), pady=5)

        result = [None]

        def tamam():
            t = tarih_var.get().strip()
            try:
                tarih_obj = datetime.strptime(t, "%d.%m.%Y")
                result[0] = (tarih_obj.strftime("%Y-%m-%d"), kurum_var.get().strip(), sinav_var.get().strip())
                dialog.destroy()
            except ValueError:
                messagebox.showerror("Hata", "Tarih formatı hatalı! GG.AA.YYYY kullanın.", parent=dialog)

        def iptal():
            dialog.destroy()

        bf = ttkb.Frame(frame)
        bf.pack(pady=(15, 0))
        ttkb.Button(bf, text="✅ Tamam", command=tamam, bootstyle="success", width=12).pack(side=LEFT, padx=5)
        ttkb.Button(bf, text="İptal", command=iptal, bootstyle="secondary", width=12).pack(side=LEFT, padx=5)

        dialog.wait_window()
        return result[0]

    def _karne_ai_analiz(self, raw_text: str, provider: str, api_key: str) -> dict:
        """PDF metnini AI ile analiz edip yapılandırılmış veri döndür."""
        prompt = f"""Aşağıda bir LGS deneme sınavı karne PDF'inden çıkartılmış metin var. Bu metinden aşağıdaki yapıda JSON veri çıkar.

## Kurallar:
- Tam olarak JSON formatında yanıt ver, başka metin ekleme
- Dersler: Türkçe, Matematik, Fen, Sosyal, İngilizce, Din (standartlaştır)
- Her ders için doğru/yanlış/boş/net bilgilerini çıkar
- Her ders altındaki konu/kazanım analizini çıkar
- Konu analizinde öğrencinin hangi konularda doğru/yanlış/boş yaptığını belirt
- Eğer kazanım bilgisi varsa (K1, K2 gibi) kazanim alanına yaz
- Eğer bazı bilgiler PDF'de yoksa 0 olarak işaretle

## İstenen JSON Formatı:
```json
{{
  "dersler": [
    {{
      "ders": "Türkçe",
      "soru_sayisi": 20,
      "dogru": 15,
      "yanlis": 3,
      "bos": 2,
      "net": 14.0,
      "basari_yuzdesi": 75.0
    }}
  ],
  "konular": [
    {{
      "ders": "Türkçe",
      "konu": "Sözcükte Anlam",
      "kazanim": "",
      "dogru": 2,
      "yanlis": 1,
      "bos": 0,
      "toplam": 3
    }}
  ],
  "ozet": "Kısa genel değerlendirme cümlesi"
}}
```

## PDF Metni:
{raw_text[:8000]}
"""

        if provider == "openai":
            from openai import OpenAI

            client = OpenAI(api_key=api_key)
            model_adi = db.oku_ayar("ai_model", "") or "gpt-4o-mini"
            response = client.chat.completions.create(
                model=model_adi,
                messages=[
                    {
                        "role": "system",
                        "content": "Sen bir PDF karne analiz uzmanısın. Sadece JSON formatında yanıt ver, markdown code block kullanma, açıklama ekleme.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=8192,
                response_format={"type": "json_object"},
            )
            yanit = self._ai_response_to_text(response.choices[0].message.content)
        else:
            import google.generativeai as genai

            genai.configure(api_key=api_key)
            model_adi = self._gemini_model_adi()
            model = genai.GenerativeModel(
                model_adi,
                system_instruction="Sen bir PDF karne analiz uzmanısın. Sadece geçerli JSON formatında yanıt ver. Markdown code block, açıklama veya ek metin ekleme.",
            )
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.1,
                    max_output_tokens=8192,
                    response_mime_type="application/json",
                ),
                request_options={"timeout": 120},
            )
            yanit = self._gemini_response_to_text(response)

        sonuc = self._parse_karne_ai_json(yanit)
        # Boş analiz durumunda gerçek AI yanıtını debug için sakla.
        # Bu alan yalnızca dahili hata ayıklama amacıyla kullanılır.
        sonuc["_raw_ai_response"] = yanit
        return sonuc

    def _ai_response_to_text(self, content) -> str:
        """SDK farkliliklarina karsi AI yanitini duz metne indirger."""
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parcalar = []
            for item in content:
                if isinstance(item, str):
                    parcalar.append(item)
                    continue
                if isinstance(item, dict):
                    text_value = item.get("text") or item.get("content")
                    if isinstance(text_value, str):
                        parcalar.append(text_value)
                    continue
                text_value = getattr(item, "text", None) or getattr(item, "content", None)
                if isinstance(text_value, str):
                    parcalar.append(text_value)
            return "".join(parcalar).strip()
        return str(content).strip()

    def _gemini_response_to_text(self, response) -> str:
        """Gemini yanitini response.text bos olsa bile candidate/part'lardan topla."""
        text_value = getattr(response, "text", None)
        if isinstance(text_value, str) and text_value.strip():
            return text_value.strip()

        parcalar = []
        for candidate in getattr(response, "candidates", []) or []:
            content = getattr(candidate, "content", None)
            for part in getattr(content, "parts", []) or []:
                part_text = getattr(part, "text", None)
                if isinstance(part_text, str) and part_text.strip():
                    parcalar.append(part_text.strip())
        return "\n".join(parcalar).strip()

    def _extract_first_json_object(self, text: str):
        """Metin icindeki ilk gecerli JSON nesnesini veya listesini bul."""
        decoder = json_module.JSONDecoder(parse_constant=lambda _value: 0)
        for match in re.finditer(r"[\{\[]", text):
            try:
                obj, _end = decoder.raw_decode(text[match.start():])
                return obj
            except json_module.JSONDecodeError:
                continue
        raise json_module.JSONDecodeError("Gecerli JSON nesnesi bulunamadi", text, 0)

    def _normalize_karne_ai_json(self, data) -> dict:
        """AI sonucunu beklenen karne semasina oturt."""
        if not isinstance(data, dict):
            data = {}

        ders_alias = {
            "turkce": "Türkçe",
            "türkçe": "Türkçe",
            "matematik": "Matematik",
            "fen": "Fen",
            "fen bilimleri": "Fen",
            "sosyal": "Sosyal",
            "sosyal bilgiler": "Sosyal",
            "ingilizce": "İngilizce",
            "i̇ngilizce": "İngilizce",
            "din": "Din",
            "din kültürü": "Din",
            "din kültürü ve ahlak bilgisi": "Din",
        }

        def temiz_metin(value, default=""):
            if value is None:
                return default
            if isinstance(value, str):
                return value.strip()
            return str(value).strip()

        def temiz_sayi(value, default=0):
            if value in (None, ""):
                return default
            if isinstance(value, (int, float)):
                return value
            text_value = str(value).strip().replace("%", "").replace(",", ".")
            try:
                number = float(text_value)
            except ValueError:
                return default
            return int(number) if float(number).is_integer() else number

        def standart_ders(value):
            text_value = temiz_metin(value)
            normalized = text_value.lower()
            return ders_alias.get(normalized, text_value)

        dersler = []
        for item in data.get("dersler") or []:
            if not isinstance(item, dict):
                continue
            dersler.append(
                {
                    "ders": standart_ders(item.get("ders")),
                    "soru_sayisi": int(temiz_sayi(item.get("soru_sayisi"), 0)),
                    "dogru": int(temiz_sayi(item.get("dogru"), 0)),
                    "yanlis": int(temiz_sayi(item.get("yanlis"), 0)),
                    "bos": int(temiz_sayi(item.get("bos"), 0)),
                    "net": float(temiz_sayi(item.get("net"), 0.0)),
                    "basari_yuzdesi": float(temiz_sayi(item.get("basari_yuzdesi"), 0.0)),
                }
            )

        konular = []
        for item in data.get("konular") or []:
            if not isinstance(item, dict):
                continue
            konular.append(
                {
                    "ders": standart_ders(item.get("ders")),
                    "konu": temiz_metin(item.get("konu")),
                    "kazanim": temiz_metin(item.get("kazanim")),
                    "dogru": int(temiz_sayi(item.get("dogru"), 0)),
                    "yanlis": int(temiz_sayi(item.get("yanlis"), 0)),
                    "bos": int(temiz_sayi(item.get("bos"), 0)),
                    "toplam": int(temiz_sayi(item.get("toplam"), 0)),
                }
            )

        return {
            "dersler": dersler,
            "konular": konular,
            "ozet": temiz_metin(data.get("ozet")),
        }

    def _debug_kaydet(self, ham_yanit: str, hata_mesaji: str):
        """Parse hatası olduğunda AI yanıtını debug dosyasına kaydet."""
        try:
            debug_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "PDFS")
            if getattr(sys, 'frozen', False):
                debug_dir = os.path.join(os.path.dirname(sys.executable), "PDFS")
            os.makedirs(debug_dir, exist_ok=True)
            zaman = datetime.now().strftime("%Y%m%d_%H%M%S")
            dosya = os.path.join(debug_dir, f"debug_ai_yanit_{zaman}.txt")
            with open(dosya, "w", encoding="utf-8") as f:
                f.write(f"=== DEBUG: AI YANIT ({zaman}) ===\n")
                f.write(f"Hata: {hata_mesaji}\n")
                f.write(f"Yanıt uzunluğu: {len(ham_yanit)} karakter\n")
                f.write(f"{'='*60}\n\n")
                f.write(ham_yanit)
            return dosya
        except Exception:
            return None

    def _json_metin_temizle(self, text: str) -> str:
        """JSON metnini temizle: BOM, Python literal, NaN, smart quote, trailing comma."""
        # BOM ve zero-width karakterler
        text = text.replace("\ufeff", "").replace("\u200b", "").replace("\u00a0", " ").strip()

        # Python literal'leri → JSON
        text = re.sub(r'\bTrue\b', 'true', text)
        text = re.sub(r'\bFalse\b', 'false', text)
        text = re.sub(r'\bNone\b', 'null', text)

        # NaN / Infinity → 0 (string dışında)
        text = re.sub(r'(?<!["\w])NaN(?!["\w])', '0', text)
        text = re.sub(r'(?<!["\w])-?Infinity(?!["\w])', '0', text)
        text = re.sub(r'(?<!["\w])nan(?!["\w])', '0', text)
        text = re.sub(r'(?<!["\w])inf(?!["\w])', '0', text)
        text = re.sub(r'(?<!["\w])-inf(?!["\w])', '0', text)

        # Smart quotes → normal quotes
        text = text.replace("\u201c", '"').replace("\u201d", '"')
        text = text.replace("\u2018", "'").replace("\u2019", "'")

        # Trailing comma temizliği (iç içe de olsa)
        text = re.sub(r',\s*([\}\]])', r'\1', text)

        return text

    def _kesik_json_onar(self, text: str) -> str:
        """Kesik JSON'u onarmayı dene (kapanmamış parantezler)."""
        acik_obje = text.count('{') - text.count('}')
        acik_dizi = text.count('[') - text.count(']')
        if acik_obje <= 0 and acik_dizi <= 0:
            return text

        # Sondaki tamamlanmamış veriyi temizle
        text = text.rstrip()
        # Açık string varsa kapat
        if text.count('"') % 2 != 0:
            son_tirnak = text.rfind('"')
            if son_tirnak > 0:
                text = text[:son_tirnak] + '"'

        # Sondaki eksik key:value temizle
        text = re.sub(r',\s*"[^"]*"\s*:\s*$', '', text)
        text = re.sub(r',\s*$', '', text)
        text = re.sub(r':\s*$', ': null', text)

        # Kalan eksik parantezleri kapat
        acik_obje = text.count('{') - text.count('}')
        acik_dizi = text.count('[') - text.count(']')
        text += '}' * max(0, acik_obje) + ']' * max(0, acik_dizi)

        return text

    def _parse_karne_ai_json(self, yanit: str) -> dict:
        """AI'dan gelen JSON benzeri yanıtı dayanıklı şekilde parse et."""
        ham_yanit = (yanit or "").strip()
        if not ham_yanit:
            raise ValueError("AI boş yanıt döndürdü.")

        hatalar = []  # Her aşamadaki hatayı topla

        # === AŞAMA 1: Temizle ve doğrudan dene ===
        temiz = self._json_metin_temizle(ham_yanit)
        try:
            data = json_module.loads(temiz, parse_constant=lambda _v: 0)
            return self._normalize_karne_ai_json(data)
        except json_module.JSONDecodeError as e:
            hatalar.append(f"Aşama 1 (doğrudan): {e.msg} (pos {e.pos})")

        # === AŞAMA 2: Code block içinden çıkar ===
        code_block = re.search(r"```(?:json)?\s*\n?(.*?)```", temiz, re.DOTALL | re.IGNORECASE)
        if code_block:
            block_text = self._json_metin_temizle(code_block.group(1).strip())
            try:
                data = json_module.loads(block_text, parse_constant=lambda _v: 0)
                return self._normalize_karne_ai_json(data)
            except json_module.JSONDecodeError as e:
                hatalar.append(f"Aşama 2 (code block): {e.msg} (pos {e.pos})")
                temiz = block_text

        # === AŞAMA 3: _extract_first_json_object ile dene ===
        try:
            obj = self._extract_first_json_object(temiz)
            return self._normalize_karne_ai_json(obj)
        except json_module.JSONDecodeError as e:
            hatalar.append(f"Aşama 3 (ilk JSON nesnesi): {e.msg}")

        # === AŞAMA 4: Kesik JSON onarımı ===
        onarilmis = self._kesik_json_onar(temiz)
        if onarilmis != temiz:
            try:
                data = json_module.loads(onarilmis, parse_constant=lambda _v: 0)
                return self._normalize_karne_ai_json(data)
            except json_module.JSONDecodeError as e:
                hatalar.append(f"Aşama 4 (kesik JSON onarım): {e.msg} (pos {e.pos})")

            try:
                obj = self._extract_first_json_object(onarilmis)
                return self._normalize_karne_ai_json(obj)
            except json_module.JSONDecodeError as e:
                hatalar.append(f"Aşama 4b (onarılmış ilk nesne): {e.msg}")

        # === BAŞARISIZ — debug dosyası kaydet ===
        hata_detay = "\n".join(hatalar)
        debug_dosya = self._debug_kaydet(ham_yanit, hata_detay)
        debug_msg = ""
        if debug_dosya:
            debug_msg = f"\n\n📁 Debug dosyası:\n{os.path.basename(debug_dosya)}"

        raise ValueError(
            f"AI yanıtı JSON olarak ayrıştırılamadı.\n\n"
            f"Denenen aşamalar:\n{hata_detay}\n\n"
            f"Yanıt başlangıcı:\n{ham_yanit[:300]}...{debug_msg}"
        )

    def _karne_kaydet(self, dosya_adi, sinav_tarihi, kurum_adi, sinav_adi, raw_text, sonuc, rag_data, progress_win):
        """AI sonucunu veritabanına kaydet."""
        try:
            progress_win.destroy()
        except Exception:
            pass

        try:
            ozet = sonuc.get("ozet", "")
            karne_id = db.karne_ekle(dosya_adi, sinav_tarihi, kurum_adi, sinav_adi, raw_text, ozet)

            for d in sonuc.get("dersler", []):
                db.karne_ders_ekle(
                    karne_id, d["ders"],
                    d.get("soru_sayisi", 0), d.get("dogru", 0),
                    d.get("yanlis", 0), d.get("bos", 0),
                    d.get("net", 0.0), d.get("basari_yuzdesi", 0.0),
                )

            for k in sonuc.get("konular", []):
                db.karne_konu_ekle(
                    karne_id, k["ders"], k["konu"],
                    k.get("kazanim", ""),
                    k.get("dogru", 0), k.get("yanlis", 0),
                    k.get("bos", 0), k.get("toplam", 0),
                )

            # RAG chunk'ları kaydet
            rag_msg = ""
            if rag_data:
                chunks, embeddings, provider = rag_data
                emb_bytes = [np.array(e, dtype=np.float32).tobytes() for e in embeddings]
                db.rag_chunks_toplu_ekle(karne_id, chunks, emb_bytes, provider)
                rag_msg = f"\n🧠 {len(chunks)} chunk bilgi bankasına eklendi"

            self._karne_listesi_guncelle()
            self._rag_durum_guncelle()
            ders_sayisi = len(sonuc.get("dersler", []))
            konu_sayisi = len(sonuc.get("konular", []))
            messagebox.showinfo("Başarılı", f"✅ Karne başarıyla kaydedildi!\n\n"
                                f"📄 {dosya_adi}\n"
                                f"📚 {ders_sayisi} ders, {konu_sayisi} konu analizi{rag_msg}")
        except Exception as e:
            messagebox.showerror("Kayıt Hatası", f"Analiz sonucu kaydedilemedi:\n{str(e)}")

    def _karne_hata(self, mesaj, progress_win):
        """Karne analiz hatası göster."""
        try:
            progress_win.destroy()
        except Exception:
            pass
        # Uzun hata mesajını kısalt (messagebox sınırlı)
        if len(mesaj) > 800:
            mesaj = mesaj[:800] + "\n\n... (devamı debug dosyasında)"
        messagebox.showerror("AI Analiz Hatası", f"Karne analiz edilemedi:\n\n{mesaj}")

    def _karne_bos_sonuc(self, dosya_adi, raw_text, sonuc, progress_win):
        """AI karneden ders/konu çıkaramadı: bilgilendir, boş (0/0) kayıt oluşturma."""
        try:
            progress_win.destroy()
        except Exception:
            pass
        n = len((raw_text or "").strip())
        # PDF metni yerine AI'nın gerçek yanıtını kaydet; boş analizde sorun
        # yanıtın içeriğinde veya beklenen alanların boş gelmesinde olabilir.
        ai_yaniti = sonuc.get("_raw_ai_response", "")
        hata_detay = (
            f"BOŞ ANALİZ — {dosya_adi} | "
            f"dersler={len(sonuc.get('dersler', []))}, "
            f"konular={len(sonuc.get('konular', []))}, "
            f"ozet={sonuc.get('ozet', '')!r}"
        )
        debug_dosya = self._debug_kaydet(ai_yaniti, hata_detay)
        extra = ""
        if debug_dosya:
            extra = f"\n\n📁 AI yanıtı ve analiz durumu debug dosyasına kaydedildi:\n{os.path.basename(debug_dosya)}"
        resim_ipucu = ""
        if n < 200:
            resim_ipucu = ("\n\n⚠️ Çıkarılan metin çok kısa — PDF büyük olasılıkla taranmış/resim "
                           "tabanlı. Bu durumda metin seçilemez; metin tabanlı (seçilebilir) bir "
                           "karne PDF'i kullanın.")
        messagebox.showwarning(
            "Karne Analiz Edilemedi",
            f"AI bu karneden ders/konu bilgisi çıkaramadı (0 ders, 0 konu).\n\n"
            f"PDF'den çıkarılan metin uzunluğu: {n} karakter.\n"
            f"Hatalı/boş kayıt oluşturulmadı.{resim_ipucu}{extra}"
        )

    def _karne_sil(self):
        """Seçili karneleri sil."""
        secili = self.karne_tree.selection()
        if not secili:
            messagebox.showwarning("Uyarı", "Lütfen silinecek karneyi seçin.")
            return

        if not messagebox.askyesno("Onay", f"{len(secili)} karne silinecek. Emin misiniz?"):
            return

        for item in secili:
            db.karne_sil(int(item))

        self._karne_listesi_guncelle()

    def _karne_secim_degisti(self, event=None):
        """Karne seçildiğinde detay göster."""
        secili = self.karne_tree.selection()
        if not secili:
            return

        karne_id = int(secili[0])
        self._karne_detay_goster(karne_id)

    def _karne_detay_goster(self, karne_id: int):
        """Seçilen karne detayını göster."""
        detay = db.karne_detay_getir(karne_id)
        if not detay:
            return

        # Detay sekmesini doldur
        for w in self.karne_detay_frame.winfo_children():
            w.destroy()

        karne = detay["karne"]
        dersler = detay["dersler"]
        konular = detay["konular"]

        # Başlık
        ttkb.Label(self.karne_detay_frame,
                   text=f"📄 {karne.get('sinav_adi', karne['dosya_adi'])}  |  {karne['sinav_tarihi']}  |  {karne.get('kurum_adi', '')}",
                   font=("Segoe UI", 11, "bold"), bootstyle="primary").pack(anchor=W, pady=(0, 5))

        if karne.get("ai_ozet"):
            ttkb.Label(self.karne_detay_frame, text=karne["ai_ozet"],
                       font=("Segoe UI", 9), bootstyle="secondary", wraplength=700).pack(anchor=W, pady=(0, 8))

        # Ders özet tablosu
        ders_tree = ttkb.Treeview(self.karne_detay_frame,
            columns=("ders", "soru", "dogru", "yanlis", "bos", "net", "basari"),
            show="headings", height=6)
        for col, txt, w in [("ders", "Ders", 100), ("soru", "Soru", 50), ("dogru", "Doğru", 50),
                            ("yanlis", "Yanlış", 50), ("bos", "Boş", 50), ("net", "Net", 60),
                            ("basari", "Başarı %", 70)]:
            ders_tree.heading(col, text=txt)
            ders_tree.column(col, width=w, minwidth=40, anchor=CENTER if col != "ders" else W)
        for d in dersler:
            tag = "iyi" if d["basari_yuzdesi"] >= 70 else ("kotu" if d["basari_yuzdesi"] < 50 else "orta")
            ders_tree.insert("", tk.END, values=(
                d["ders"], d["soru_sayisi"], d["dogru"], d["yanlis"], d["bos"],
                f"{d['net']:.1f}", f"%{d['basari_yuzdesi']:.0f}"
            ), tags=(tag,))
        ders_tree.tag_configure("iyi", background="#d5f5e3")
        ders_tree.tag_configure("orta", background="#fdebd0")
        ders_tree.tag_configure("kotu", background="#fadbd8")
        ders_tree.pack(fill=X, pady=(0, 8))

        # Konu detay tablosu
        if konular:
            ttkb.Label(self.karne_detay_frame, text="📖 Konu Detayları",
                       font=("Segoe UI", 10, "bold")).pack(anchor=W, pady=(5, 3))

            konu_frame = ttkb.Frame(self.karne_detay_frame)
            konu_frame.pack(fill=BOTH, expand=True)

            konu_tree = ttkb.Treeview(konu_frame,
                columns=("ders", "konu", "dogru", "yanlis", "bos", "toplam"),
                show="headings", height=10)
            for col, txt, w in [("ders", "Ders", 90), ("konu", "Konu", 250),
                                ("dogru", "✓", 45), ("yanlis", "✗", 45),
                                ("bos", "—", 45), ("toplam", "Top.", 45)]:
                konu_tree.heading(col, text=txt)
                konu_tree.column(col, width=w, minwidth=35, anchor=CENTER if col not in ("ders", "konu") else W)

            konu_scroll = ttkb.Scrollbar(konu_frame, orient=VERTICAL, command=konu_tree.yview)
            konu_tree.configure(yscrollcommand=konu_scroll.set)
            konu_tree.pack(side=LEFT, fill=BOTH, expand=True)
            konu_scroll.pack(side=RIGHT, fill=Y)

            for k in konular:
                tag = ""
                if k["yanlis"] > 0:
                    tag = "hatali"
                elif k["bos"] > 0:
                    tag = "bos"
                else:
                    tag = "dogru"
                konu_tree.insert("", tk.END, values=(
                    k["ders"], k["konu"], k["dogru"], k["yanlis"], k["bos"], k["toplam"]
                ), tags=(tag,))
            konu_tree.tag_configure("hatali", background="#fadbd8")
            konu_tree.tag_configure("bos", background="#fef9e7")
            konu_tree.tag_configure("dogru", background="#d5f5e3")

    def _karne_analiz_goster(self):
        """Filtrelenmiş analiz raporlarını göster."""
        son_gun = self._karne_donem_gun()
        ders = self.karne_ders_var.get()

        # Veri kontrolü
        karneler = db.karneleri_getir(son_gun)
        if not karneler:
            messagebox.showinfo("Bilgi", "Seçili dönemde karne bulunamadı.\n\n"
                               "Önce 'PDF Yükle' butonuyla karne yükleyin.")
            return

        self._karne_konu_raporu_goster(son_gun, ders)
        self._karne_ders_ozet_goster(son_gun, ders)
        self._karne_gelisim_goster(ders)

        # Konu Hata Raporu sekmesine geç
        self.karne_notebook.select(0)

    def _karne_konu_raporu_goster(self, son_gun, ders):
        """Konu bazlı hata raporu."""
        for w in self.karne_konu_frame.winfo_children():
            w.destroy()

        rapor = db.karne_konu_raporu(son_gun, ders)
        if not rapor:
            ttkb.Label(self.karne_konu_frame, text="📭 Henüz karne verisi yok.\nPDF yükleyerek başlayın.",
                       font=("Segoe UI", 12), bootstyle="secondary").pack(expand=True)
            return

        donem_str = self.karne_donem_var.get()
        ders_str = ders if ders != "Tümü" else "Tüm Dersler"

        ttkb.Label(self.karne_konu_frame,
                   text=f"❌ Konu Hata Raporu — {ders_str} ({donem_str})",
                   font=("Segoe UI", 11, "bold"), bootstyle="danger").pack(anchor=W, pady=(0, 5))

        ttkb.Label(self.karne_konu_frame,
                   text="Hata oranına göre sıralı — en çok hata yapılan konular üstte",
                   font=("Segoe UI", 8), bootstyle="secondary").pack(anchor=W, pady=(0, 5))

        # Treeview
        tree_frame = ttkb.Frame(self.karne_konu_frame)
        tree_frame.pack(fill=BOTH, expand=True)

        cols = ("ders", "konu", "hata_orani", "yanlis", "bos", "dogru", "toplam", "karne_s")
        tree = ttkb.Treeview(tree_frame, columns=cols, show="headings", height=18)
        for col, txt, w in [
            ("ders", "Ders", 85), ("konu", "Konu", 220), ("hata_orani", "Hata %", 65),
            ("yanlis", "Yanlış", 55), ("bos", "Boş", 45), ("dogru", "Doğru", 55),
            ("toplam", "Toplam", 55), ("karne_s", "Karne#", 55)
        ]:
            tree.heading(col, text=txt)
            anc = CENTER if col not in ("ders", "konu") else W
            tree.column(col, width=w, minwidth=35, anchor=anc)

        scroll = ttkb.Scrollbar(tree_frame, orient=VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side=LEFT, fill=BOTH, expand=True)
        scroll.pack(side=RIGHT, fill=Y)

        # Hata oranına göre sırala (yüksek→düşük)
        rapor.sort(key=lambda x: x["hata_orani"], reverse=True)

        for r in rapor:
            tag = "kritik" if r["hata_orani"] >= 70 else ("uyari" if r["hata_orani"] >= 40 else "iyi")
            tree.insert("", tk.END, values=(
                r["ders"], r["konu"], f"%{r['hata_orani']:.0f}",
                r["toplam_yanlis"], r["toplam_bos"], r["toplam_dogru"],
                r["toplam_soru"], r["karne_sayisi"],
            ), tags=(tag,))

        tree.tag_configure("kritik", background="#fadbd8", foreground="#922b21")
        tree.tag_configure("uyari", background="#fdebd0", foreground="#935116")
        tree.tag_configure("iyi", background="#d5f5e3")

        # Özet istatistik
        toplam_konu = len(rapor)
        kritik = len([r for r in rapor if r["hata_orani"] >= 70])
        uyari = len([r for r in rapor if 40 <= r["hata_orani"] < 70])

        ozet_frame = ttkb.Frame(self.karne_konu_frame)
        ozet_frame.pack(fill=X, pady=(5, 0))
        ttkb.Label(ozet_frame, text=f"Toplam {toplam_konu} konu  |  ",
                   font=("Segoe UI", 9)).pack(side=LEFT)
        ttkb.Label(ozet_frame, text=f"🔴 Kritik: {kritik}  |  ",
                   font=("Segoe UI", 9, "bold"), foreground="#e74c3c").pack(side=LEFT)
        ttkb.Label(ozet_frame, text=f"🟡 Uyarı: {uyari}  |  ",
                   font=("Segoe UI", 9, "bold"), foreground="#f39c12").pack(side=LEFT)
        ttkb.Label(ozet_frame, text=f"🟢 İyi: {toplam_konu - kritik - uyari}",
                   font=("Segoe UI", 9, "bold"), foreground="#27ae60").pack(side=LEFT)

    def _karne_ders_ozet_goster(self, son_gun, ders):
        """Ders bazlı özet grafik ve tablo."""
        for w in self.karne_ders_frame.winfo_children():
            w.destroy()

        karneler = db.karneleri_getir(son_gun)
        if not karneler:
            ttkb.Label(self.karne_ders_frame, text="📭 Henüz karne verisi yok.",
                       font=("Segoe UI", 12), bootstyle="secondary").pack(expand=True)
            return

        # Tüm karne ders verilerini topla
        ders_toplam = {}
        for k in karneler:
            detay = db.karne_detay_getir(k["id"])
            if not detay:
                continue
            for d in detay["dersler"]:
                if ders != "Tümü" and d["ders"] != ders:
                    continue
                key = d["ders"]
                if key not in ders_toplam:
                    ders_toplam[key] = {"soru": 0, "dogru": 0, "yanlis": 0, "bos": 0, "net": 0.0, "sayac": 0}
                ders_toplam[key]["soru"] += d["soru_sayisi"]
                ders_toplam[key]["dogru"] += d["dogru"]
                ders_toplam[key]["yanlis"] += d["yanlis"]
                ders_toplam[key]["bos"] += d["bos"]
                ders_toplam[key]["net"] += d["net"]
                ders_toplam[key]["sayac"] += 1

        if not ders_toplam:
            ttkb.Label(self.karne_ders_frame, text="📭 Seçili filtreye uygun veri yok.",
                       font=("Segoe UI", 12), bootstyle="secondary").pack(expand=True)
            return

        donem_str = self.karne_donem_var.get()
        ttkb.Label(self.karne_ders_frame,
                   text=f"📊 Ders Başarı Özeti ({donem_str})",
                   font=("Segoe UI", 11, "bold"), bootstyle="info").pack(anchor=W, pady=(0, 5))

        # Matplotlib grafik
        fig = Figure(figsize=(8, 3.5), dpi=100)
        fig.patch.set_facecolor("#f8f9fa")
        ax = fig.add_subplot(111)
        ax.set_facecolor("#ffffff")

        dersler_s = sorted(ders_toplam.keys())
        basari_listesi = []
        renkler = []
        for d_adi in dersler_s:
            dt = ders_toplam[d_adi]
            basari = (dt["dogru"] / max(1, dt["soru"]) * 100)
            basari_listesi.append(basari)
            renkler.append(DERS_RENKLERI.get(d_adi, "#999"))

        bars = ax.bar(dersler_s, basari_listesi, color=renkler, width=0.6, edgecolor="white", linewidth=1.5)
        for bar, val in zip(bars, basari_listesi):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                    f"%{val:.0f}", ha="center", fontsize=9, fontweight="bold")

        ax.set_ylim(0, 110)
        ax.set_ylabel("Başarı %", fontsize=10)
        ax.set_title("Ders Bazlı Ortalama Başarı", fontsize=12, fontweight="bold")
        ax.axhline(y=70, color="#27ae60", linestyle="--", alpha=0.5, label="Hedef %70")
        ax.axhline(y=50, color="#e74c3c", linestyle="--", alpha=0.3, label="Risk %50")
        ax.legend(fontsize=8)
        ax.grid(True, axis="y", alpha=0.3)
        fig.tight_layout()

        canvas = FigureCanvasTkAgg(fig, master=self.karne_ders_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=BOTH, expand=True)

    def _karne_gelisim_goster(self, ders):
        """Karne bazlı gelişim grafiği."""
        for w in self.karne_gelisim_frame.winfo_children():
            w.destroy()

        rapor = db.karne_gelisim_raporu(ders)
        if not rapor:
            ttkb.Label(self.karne_gelisim_frame, text="📭 Gelişim raporu için en az 2 karne gerekli.",
                       font=("Segoe UI", 12), bootstyle="secondary").pack(expand=True)
            return

        df = pd.DataFrame(rapor)
        df["tarih"] = pd.to_datetime(df["sinav_tarihi"])

        ttkb.Label(self.karne_gelisim_frame,
                   text="📈 Karne Başarı Gelişim Grafiği",
                   font=("Segoe UI", 11, "bold"), bootstyle="success").pack(anchor=W, pady=(0, 5))

        fig = Figure(figsize=(8, 4), dpi=100)
        fig.patch.set_facecolor("#f8f9fa")
        ax = fig.add_subplot(111)
        ax.set_facecolor("#ffffff")

        aktif_dersler = df["ders"].unique()
        for d_adi in aktif_dersler:
            ders_df = df[df["ders"] == d_adi].sort_values("tarih")
            renk = DERS_RENKLERI.get(d_adi, "#999")
            ax.plot(ders_df["tarih"], ders_df["basari"], marker="o", label=d_adi,
                    color=renk, linewidth=2, markersize=6)

            # Veri noktası değerleri
            for _, row in ders_df.iterrows():
                ax.annotate(f"%{row['basari']:.0f}", (row["tarih"], row["basari"]),
                           textcoords="offset points", xytext=(0, 8), ha="center",
                           fontsize=7, fontweight="bold", color=renk)

            # Trend çizgisi
            if len(ders_df) >= 3:
                window = min(3, len(ders_df))
                ders_df = ders_df.copy()
                ders_df["trend"] = ders_df["basari"].rolling(window=window, min_periods=1).mean()
                ax.plot(ders_df["tarih"], ders_df["trend"], linestyle="--",
                        color=renk, linewidth=2, alpha=0.6)

        ax.set_title("Karne Başarı Trendi", fontsize=13, fontweight="bold", pad=10)
        ax.set_xlabel("Sınav Tarihi", fontsize=10)
        ax.set_ylabel("Başarı %", fontsize=10)
        ax.legend(loc="best", fontsize=8, ncol=2)
        ax.grid(True, alpha=0.3)
        ax.axhline(y=70, color="#27ae60", linestyle=":", alpha=0.4)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m.%y"))
        fig.autofmt_xdate()
        fig.tight_layout()

        canvas = FigureCanvasTkAgg(fig, master=self.karne_gelisim_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=BOTH, expand=True)

        toolbar = NavigationToolbar2Tk(canvas, self.karne_gelisim_frame)
        toolbar.update()

    # =====================================================
    # RAG (BİLGİ BANKASI) SİSTEMİ
    # =====================================================
    def _build_rag_tab(self):
        """Bilgi Bankası (RAG) alt sekmesini oluştur."""
        frame = self.karne_rag_frame

        # Üst bilgi
        info_frame = ttkb.Frame(frame)
        info_frame.pack(fill=X, pady=(0, 8))

        self.rag_durum_label = ttkb.Label(
            info_frame, text="📚 Bilgi bankası boş — PDF yükleyerek başlayın",
            font=("Segoe UI", 9), bootstyle="secondary")
        self.rag_durum_label.pack(side=LEFT)

        ttkb.Button(
            info_frame, text="🔄 Tümünü Yeniden Embed Et",
            command=self._rag_yeniden_embed, bootstyle="warning-outline", width=24,
        ).pack(side=RIGHT, padx=5)

        # Soru alanı
        soru_frame = ttkb.Labelframe(frame, text="🔍 Bilgi Bankasına Soru Sor", padding=10, bootstyle="primary")
        soru_frame.pack(fill=X, pady=(0, 8))

        soru_input = ttkb.Frame(soru_frame)
        soru_input.pack(fill=X)

        self.rag_soru_var = tk.StringVar()
        soru_entry = ttkb.Entry(soru_input, textvariable=self.rag_soru_var,
                                font=("Segoe UI", 11), width=60)
        soru_entry.pack(side=LEFT, fill=X, expand=True, padx=(0, 8))
        soru_entry.bind("<Return>", lambda e: self._rag_sorgula())

        self.rag_sorgula_btn = ttkb.Button(
            soru_input, text="🔍 Sorgula", command=self._rag_sorgula,
            bootstyle="success", width=12)
        self.rag_sorgula_btn.pack(side=LEFT)

        # Örnek sorular
        ornek_frame = ttkb.Frame(soru_frame)
        ornek_frame.pack(fill=X, pady=(8, 0))

        ttkb.Label(ornek_frame, text="Örnek:", font=("Segoe UI", 8),
                   bootstyle="secondary").pack(side=LEFT, padx=(0, 5))

        ornekler = [
            "En çok hata yapılan konular",
            "Matematik performansı nasıl?",
            "Hangi derslerde gelişim var?",
            "Zayıf konuları analiz et",
        ]
        for ornek in ornekler:
            btn = ttkb.Button(
                ornek_frame, text=ornek,
                command=lambda s=ornek: self._rag_ornek_sec(s),
                bootstyle="info-outline", width=len(ornek) + 2,
            )
            btn.pack(side=LEFT, padx=2)

        # Yanıt alanı
        yanit_frame = ttkb.Labelframe(frame, text="🤖 AI Yanıtı", padding=10, bootstyle="info")
        yanit_frame.pack(fill=BOTH, expand=True)

        self.rag_text = tk.Text(
            yanit_frame, wrap=tk.WORD, font=("Segoe UI", 10),
            bg="#f0f4f8", fg="#2c3e50", relief=tk.FLAT,
            padx=15, pady=15, spacing1=2, spacing2=2, spacing3=4)
        rag_scroll = ttkb.Scrollbar(yanit_frame, orient=VERTICAL, command=self.rag_text.yview)
        self.rag_text.configure(yscrollcommand=rag_scroll.set)
        self.rag_text.pack(side=LEFT, fill=BOTH, expand=True)
        rag_scroll.pack(side=RIGHT, fill=Y)

        # Text tag'leri
        self.rag_text.tag_configure("rag_baslik", font=("Segoe UI", 13, "bold"), foreground="#1a5276")
        self.rag_text.tag_configure("rag_alt", font=("Segoe UI", 11, "bold"), foreground="#2e86c1")
        self.rag_text.tag_configure("rag_normal", font=("Segoe UI", 10), foreground="#2c3e50")
        self.rag_text.tag_configure("rag_vurgu", font=("Segoe UI", 10, "bold"), foreground="#117a65")
        self.rag_text.tag_configure("rag_meta", font=("Segoe UI", 8), foreground="#95a5a6")

        # Başlangıç mesajı
        self.rag_text.insert(tk.END, "🔍 Bilgi Bankası\n", "rag_baslik")
        self.rag_text.insert(tk.END, "━" * 50 + "\n\n", "rag_meta")
        self.rag_text.insert(tk.END, "PDF karneleriniz yüklendikçe bilgi bankası otomatik oluşturulur.\n", "rag_normal")
        self.rag_text.insert(tk.END, "Tüm karnelerdeki bilgilere karşı soru sorabilirsiniz.\n\n", "rag_normal")
        self.rag_text.insert(tk.END, "Örnek sorular:\n", "rag_alt")
        self.rag_text.insert(tk.END, "  • Matematik'te en çok hata yapılan konular neler?\n", "rag_normal")
        self.rag_text.insert(tk.END, "  • Fen bilimlerinde gelişim nasıl?\n", "rag_normal")
        self.rag_text.insert(tk.END, "  • Genel güçlü ve zayıf yönleri analiz et\n", "rag_normal")
        self.rag_text.insert(tk.END, "  • Son sınavlarda hangi derslerde ilerleme var?\n", "rag_normal")
        self.rag_text.configure(state=tk.DISABLED)

        self._rag_durum_guncelle()

    def _rag_durum_guncelle(self):
        """RAG bilgi bankası durum etiketini güncelle."""
        try:
            stats = db.rag_chunk_sayisi()
            if stats["chunk_sayisi"] > 0:
                self.rag_durum_label.configure(
                    text=f"📚 {stats['karne_sayisi']} karne, {stats['chunk_sayisi']} bilgi parçası hazır",
                    bootstyle="success")
            else:
                self.rag_durum_label.configure(
                    text="📚 Bilgi bankası boş — PDF yükleyerek başlayın",
                    bootstyle="secondary")
        except Exception:
            pass

    def _rag_ornek_sec(self, soru: str):
        """Örnek soruyu seç ve sorgula."""
        self.rag_soru_var.set(soru)
        self._rag_sorgula()

    def _rag_chunk_text(self, text: str, chunk_size: int = 500, overlap: int = 100) -> list:
        """Metni chunk'lara böl."""
        text = text.strip()
        if not text:
            return []

        # Paragraf bazlı bölme dene
        paragraphs = re.split(r'\n\s*\n', text)
        chunks = []
        current_chunk = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            if len(current_chunk) + len(para) + 2 <= chunk_size:
                current_chunk += ("\n\n" if current_chunk else "") + para
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                # Paragraf çok uzunsa karakter bazlı böl
                if len(para) > chunk_size:
                    start = 0
                    while start < len(para):
                        end = min(start + chunk_size, len(para))
                        chunks.append(para[start:end])
                        start += chunk_size - overlap
                else:
                    current_chunk = para

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    def _rag_embed_text(self, text: str, provider: str, api_key: str) -> list:
        """Tek metin embedding."""
        if provider == "openai":
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            response = client.embeddings.create(
                model="text-embedding-3-small",
                input=text[:8000])
            return response.data[0].embedding
        else:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            result = genai.embed_content(
                model="models/text-embedding-004",
                content=text[:8000])
            return result['embedding']

    def _rag_embed_chunks(self, chunks: list, provider: str, api_key: str) -> list:
        """Chunk listesi için toplu embedding."""
        if not chunks:
            return []

        try:
            if provider == "openai":
                from openai import OpenAI
                client = OpenAI(api_key=api_key)
                response = client.embeddings.create(
                    model="text-embedding-3-small",
                    input=[c[:8000] for c in chunks])
                return [item.embedding for item in response.data]
            else:
                import google.generativeai as genai
                genai.configure(api_key=api_key)
                result = genai.embed_content(
                    model="models/text-embedding-004",
                    content=[c[:8000] for c in chunks])
                return result['embedding']
        except Exception:
            # Toplu başarısızsa tek tek dene
            embeddings = []
            for chunk in chunks:
                try:
                    emb = self._rag_embed_text(chunk, provider, api_key)
                    embeddings.append(emb)
                except Exception:
                    return []  # Embedding desteklenmiyor
            return embeddings

    def _rag_cosine_similarity(self, a, b):
        """Cosine similarity hesapla."""
        a = np.array(a, dtype=np.float32)
        b = np.array(b, dtype=np.float32)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    def _rag_sorgula(self):
        """Bilgi bankasına soru sor."""
        soru = self.rag_soru_var.get().strip()
        if not soru:
            messagebox.showwarning("Uyarı", "Lütfen bir soru yazın.")
            return

        provider = db.oku_ayar("ai_provider", "gemini")
        api_key = db.oku_ayar(f"{provider}_api_key", "")
        if not api_key:
            messagebox.showwarning("API Gerekli",
                "Bilgi bankası sorgulamak için API anahtarı gereklidir.\n"
                "Ayarlar → AI API Ayarları menüsünden girin.")
            return

        stats = db.rag_chunk_sayisi(provider)
        if stats["chunk_sayisi"] == 0:
            # Embedding yoksa raw text ile fallback
            karneler = db.rag_tum_raw_text()
            if not karneler:
                messagebox.showinfo("Bilgi Bankası Boş",
                    "Henüz PDF karne yüklenmemiş.\nÖnce PDF yükleyin.")
                return
            # Embedding olmadan direkt ham metin ile sorgu yap
            self._rag_sorgula_fallback(soru, karneler, provider, api_key)
            return

        # UI güncelle
        self.rag_sorgula_btn.configure(state=tk.DISABLED, text="⏳ Sorgulanıyor...")
        self.rag_text.configure(state=tk.NORMAL)
        self.rag_text.delete("1.0", tk.END)
        self.rag_text.insert(tk.END, "⏳ Bilgi bankası sorgulanıyor...\n", "rag_baslik")
        self.rag_text.configure(state=tk.DISABLED)

        def islem():
            try:
                # 1. Soruyu embed et
                soru_emb = self._rag_embed_text(soru, provider, api_key)

                # 2. Tüm chunk'ları al
                chunks = db.rag_tum_chunklar(provider)

                # 3. Cosine similarity hesapla
                scored = []
                for chunk in chunks:
                    chunk_emb = np.frombuffer(chunk["embedding"], dtype=np.float32)
                    sim = self._rag_cosine_similarity(soru_emb, chunk_emb)
                    scored.append((sim, chunk))

                # 4. En ilgili chunk'ları seç (top-K)
                scored.sort(key=lambda x: x[0], reverse=True)
                top_k = scored[:8]

                # 5. Context oluştur
                context_parts = []
                for score, chunk in top_k:
                    kaynak = f"[{chunk.get('dosya_adi', '?')} - {chunk.get('sinav_adi', '?')}]"
                    context_parts.append(f"{kaynak}\n{chunk['chunk_text']}")

                context = "\n\n---\n\n".join(context_parts)

                # 6. AI'ya gönder
                yanit = self._rag_ai_sorgula(soru, context, provider, api_key)

                self.root.after(0, lambda: self._rag_sonuc_goster(yanit, len(top_k)))
            except Exception as e:
                self.root.after(0, lambda: self._rag_sonuc_goster(
                    f"❌ Sorgu hatası:\n{str(e)}", 0))

        thread = threading.Thread(target=islem, daemon=True)
        thread.start()

    def _rag_sorgula_fallback(self, soru: str, karneler: list, provider: str, api_key: str):
        """Embedding olmadan ham metin ile sorgu yap (fallback)."""
        self.rag_sorgula_btn.configure(state=tk.DISABLED, text="⏳ Sorgulanıyor...")
        self.rag_text.configure(state=tk.NORMAL)
        self.rag_text.delete("1.0", tk.END)
        self.rag_text.insert(tk.END, "⏳ Karneler analiz ediliyor (RAG embedding yok, direkt metin)...\n", "rag_baslik")
        self.rag_text.configure(state=tk.DISABLED)

        def islem():
            try:
                # Tüm raw text'leri birleştir (max 12000 karakter)
                combined = ""
                for k in karneler:
                    raw = k.get("raw_text", "")
                    header = f"\n=== {k['dosya_adi']} ===\n"
                    if len(combined) + len(header) + len(raw) < 12000:
                        combined += header + raw + "\n"
                    else:
                        remaining = 12000 - len(combined) - len(header)
                        if remaining > 200:
                            combined += header + raw[:remaining] + "\n"
                        break

                yanit = self._rag_ai_sorgula(soru, combined, provider, api_key)
                self.root.after(0, lambda: self._rag_sonuc_goster(yanit, len(karneler)))
            except Exception as e:
                self.root.after(0, lambda: self._rag_sonuc_goster(
                    f"❌ Sorgu hatası:\n{str(e)}", 0))

        thread = threading.Thread(target=islem, daemon=True)
        thread.start()

    def _rag_ai_sorgula(self, soru: str, context: str, provider: str, api_key: str) -> str:
        """RAG sorgusu: context + soru → AI yanıt."""
        prompt = f"""Aşağıda bir öğrencinin LGS deneme sınavı karnelerinden çıkarılmış bilgiler var.
Bu bilgileri kullanarak soruyu detaylı ve Türkçe olarak yanıtla.

## Karne Bilgileri:
{context[:10000]}

## Soru:
{soru}

## Kurallar:
- Sadece verilen karne bilgilerine dayanarak yanıt ver
- Somut veriler ve yüzdeler kullan
- Emoji kullanarak okunabilirliği artır
- LGS perspektifinden değerlendir
- Öneriler sun
"""
        if provider == "openai":
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            model_adi = db.oku_ayar("ai_model", "") or "gpt-4o-mini"
            response = client.chat.completions.create(
                model=model_adi,
                messages=[
                    {"role": "system", "content": "Sen bir LGS eğitim uzmanısın. Öğrencinin karne verilerini analiz edip Türkçe yanıt veriyorsun."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.5,
                max_tokens=4096)
            return response.choices[0].message.content or "Yanıt üretilemedi."
        else:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            model_adi = self._gemini_model_adi()
            model = genai.GenerativeModel(model_adi)
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.5, max_output_tokens=4096),
                request_options={"timeout": 120})
            return self._gemini_response_to_text(response) or "Yanıt üretilemedi."

    def _rag_sonuc_goster(self, yanit: str, kaynak_sayisi: int):
        """RAG sorgu sonucunu göster."""
        self.rag_sorgula_btn.configure(state=tk.NORMAL, text="🔍 Sorgula")
        self.rag_text.configure(state=tk.NORMAL)
        self.rag_text.delete("1.0", tk.END)

        self.rag_text.insert(tk.END, "🤖 AI Yanıtı\n", "rag_baslik")
        self.rag_text.insert(tk.END, "━" * 50 + "\n\n", "rag_meta")

        # Basit markdown render
        lines = yanit.split("\n")
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("### "):
                self.rag_text.insert(tk.END, stripped[4:] + "\n", "rag_alt")
            elif stripped.startswith("## "):
                self.rag_text.insert(tk.END, stripped[3:] + "\n", "rag_baslik")
            elif stripped.startswith("# "):
                self.rag_text.insert(tk.END, stripped[2:] + "\n", "rag_baslik")
            elif stripped.startswith("**") and stripped.endswith("**"):
                self.rag_text.insert(tk.END, stripped[2:-2] + "\n", "rag_alt")
            else:
                # inline **bold**
                parts = line.split("**")
                for i, part in enumerate(parts):
                    tag = "rag_vurgu" if i % 2 == 1 else "rag_normal"
                    self.rag_text.insert(tk.END, part, tag)
                self.rag_text.insert(tk.END, "\n", "rag_normal")

        self.rag_text.insert(tk.END, f"\n{'━' * 50}\n", "rag_meta")
        self.rag_text.insert(tk.END, f"📊 {kaynak_sayisi} kaynak kullanıldı | "
                             f"{datetime.now().strftime('%H:%M:%S')}\n", "rag_meta")
        self.rag_text.configure(state=tk.DISABLED)

    def _rag_yeniden_embed(self):
        """Tüm karneleri yeniden chunk'la ve embed et."""
        provider = db.oku_ayar("ai_provider", "gemini")
        api_key = db.oku_ayar(f"{provider}_api_key", "")
        if not api_key:
            messagebox.showwarning("API Gerekli",
                "Embedding için API anahtarı gereklidir.")
            return

        karneler = db.rag_tum_raw_text()
        if not karneler:
            messagebox.showinfo("Bilgi", "Yeniden embed edilecek karne yok.")
            return

        confirm = messagebox.askyesno("Onay",
            f"{len(karneler)} karne yeniden embed edilecek.\n"
            f"Bu işlem API kotası kullanır. Devam edilsin mi?")
        if not confirm:
            return

        # Progress
        progress_win = tk.Toplevel(self.root)
        progress_win.title("⏳ Yeniden Embedding...")
        progress_win.geometry("400x120")
        progress_win.resizable(False, False)
        progress_win.transient(self.root)
        progress_win.grab_set()
        progress_win.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - 400) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 120) // 2
        progress_win.geometry(f"+{x}+{y}")

        pf = ttkb.Frame(progress_win, padding=20)
        pf.pack(fill=BOTH, expand=True)
        status_label = ttkb.Label(pf, text="Embedding başlatılıyor...", font=("Segoe UI", 10))
        status_label.pack()
        pb = ttkb.Progressbar(pf, mode="determinate", bootstyle="info", maximum=len(karneler))
        pb.pack(fill=X, pady=10)
        progress_win.update()

        def islem():
            try:
                # Eski chunk'ları temizle
                db.rag_provider_temizle(provider)

                basarili = 0
                for i, karne in enumerate(karneler):
                    try:
                        chunks = self._rag_chunk_text(karne["raw_text"])
                        embeddings = self._rag_embed_chunks(chunks, provider, api_key)
                        if embeddings:
                            emb_bytes = [np.array(e, dtype=np.float32).tobytes() for e in embeddings]
                            db.rag_chunks_toplu_ekle(karne["id"], chunks, emb_bytes, provider)
                            basarili += 1
                    except Exception:
                        pass

                    self.root.after(0, lambda idx=i+1, name=karne["dosya_adi"]:
                        (status_label.configure(text=f"{idx}/{len(karneler)}: {name}"),
                         pb.configure(value=idx),
                         progress_win.update()))

                self.root.after(0, lambda: (
                    progress_win.destroy(),
                    self._rag_durum_guncelle(),
                    messagebox.showinfo("Tamamlandı",
                        f"✅ {basarili}/{len(karneler)} karne embed edildi.")
                ))
            except Exception as e:
                self.root.after(0, lambda: (
                    progress_win.destroy(),
                    messagebox.showerror("Hata", f"Embedding hatası:\n{str(e)}")
                ))

        thread = threading.Thread(target=islem, daemon=True)
        thread.start()

    def run(self):
        """Uygulamayı başlat."""
        self.root.mainloop()


if __name__ == "__main__":
    try:
        app = LGSTakipApp()
        app.run()
    except Exception as exc:
        messagebox.showerror(
            "Uygulama başlatılamadı",
            "Yerel veritabanı hazırlanırken bir hata oluştu. EXE yanındaki "
            "lgs_takip.db dosyasına yazma izni olduğundan emin olun.\n\n"
            f"Hata: {type(exc).__name__}: {exc}",
        )
