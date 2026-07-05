const express = require("express");
const router = express.Router();

const users = [
  { id: 1, name: "Alice", email: "alice@example.com", role: "admin" },
  { id: 2, name: "Bob", email: "bob@example.com", role: "user" },
  { id: 3, name: "Charlie", email: "charlie@example.com", role: "user" },
];

router.get("/", (req, res) => {
  res.json(users);
});

module.exports = router;
