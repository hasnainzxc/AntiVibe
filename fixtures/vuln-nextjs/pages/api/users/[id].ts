import { NextApiRequest, NextApiResponse } from "next";

const users = [
  { id: 1, name: "Alice", email: "alice@example.com", role: "admin" },
  { id: 2, name: "Bob", email: "bob@example.com", role: "user" },
  { id: 3, name: "Charlie", email: "charlie@example.com", role: "user" },
];

export default function handler(req: NextApiRequest, res: NextApiResponse) {
  const { id } = req.query;
  const user = users.find((u) => u.id === Number(id));
  if (!user) {
    return res.status(404).json({ error: "User not found" });
  }
  return res.status(200).json(user);
}
