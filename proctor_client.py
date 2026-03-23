import tkinter as tk
from tkinter import messagebox
import requests

# --- CONFIGURATION ---
DEFAULT_PORT = "6000"

def connect_to_student():
    entered_address = ip_entry.get().strip()
    
    if not entered_address:
        messagebox.showerror("Error", "Please enter a Student IP or Cloudflare Link")
        return

    # LOGIC: Check if it's a Cloudflare link or a regular IP
    if "trycloudflare.com" in entered_address:
        # Cloudflare uses HTTPS and handles the port for you
        if not entered_address.startswith("https://"):
            target_url = f"https://{entered_address}"
        else:
            target_url = entered_address
    else:
        # Regular IP address needs the port 6000
        target_url = f"http://{entered_address}:{DEFAULT_PORT}"

    try:
        # Test the connection to the server
        response = requests.get(target_url, timeout=5)
        if response.status_code == 200:
            messagebox.showinfo("Success", f"Connected to: {target_url}")
            # Here is where your code would normally open the camera/monitoring window
        else:
            messagebox.showwarning("Issue", f"Server responded with code: {response.status_code}")
            
    except requests.exceptions.RequestException as e:
        messagebox.showerror("Connection Failed", 
            f"Cannot reach: {target_url}\n\n"
            "1. Is the student's main.py running?\n"
            "2. Is the Cloudflare/ngrok terminal still open?\n"
            "3. Check your internet connection.")

# --- GUI SETUP ---
root = tk.Tk()
root.title("ExamShield — Remote Proctor")
root.geometry("400x300")
root.configure(bg='#121b22')

label = tk.Label(root, text="ExamShield Remote Proctor", fg="#ff6b81", bg="#121b22", font=("Arial", 16, "bold"))
label.pack(pady=20)

instruction = tk.Label(root, text="Enter the IP or Cloudflare link:", fg="white", bg="#121b22")
instruction.pack()

ip_entry = tk.Entry(root, width=30, font=("Arial", 12))
ip_entry.pack(pady=10)
ip_entry.insert(0, "paste-link-here.trycloudflare.com")

connect_btn = tk.Button(root, text="Connect ▶", command=connect_to_student, bg="#00e676", fg="black", font=("Arial", 12, "bold"), width=15)
connect_btn.pack(pady=20)

root.mainloop()