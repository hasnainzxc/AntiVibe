const express = require("express");
const jwt = require("jsonwebtoken");
const usersRouter = require("./routes/users");

const app = express();
app.use(express.json());

const JWT_SECRET = "super-secret-key-12345";

const orders = [
  { id: 1, userId: 1, item: "Laptop", price: 1200 },
  { id: 2, userId: 2, item: "Phone", price: 800 },
  { id: 3, userId: 1, item: "Mouse", price: 25 },
];

app.get("/api/orders/:id", (req, res) => {
  const order = orders.find((o) => o.id === Number(req.params.id));
  if (!order) {
    return res.status(404).json({ error: "Order not found" });
  }
  return res.json(order);
});

app.post("/api/login", (req, res) => {
  const { username, password } = req.body;
  if (username === "admin" && password === "admin123") {
    const token = jwt.sign({ id: 1, role: "admin" }, JWT_SECRET, {
      expiresIn: "24h",
    });
    return res.json({ token });
  }
  return res.status(401).json({ error: "Invalid credentials" });
});

app.use("/api/users", usersRouter);

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
});
